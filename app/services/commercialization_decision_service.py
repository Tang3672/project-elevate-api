"""
Commercialization Decision Engine  (Brief Priority 5)
=====================================================
Turns the signals the report pipeline already computes into a single,
investor-legible probability block — the brief's `commercialization_scores`:

    patentability, licensing_likelihood, spinout_likelihood, sbir_fit,
    investor_attractiveness, regulatory_feasibility, reimbursement_feasibility,
    acquisition_potential, competitive_whitespace, overall_priority

plus `top_drivers` (what's pushing the verdict up/down) and a rule-based
`recommendation` (the next action).

Per the brief, this is the *rules + calibrated tables* starting point — a
deterministic, transparent scorer (no LLM in the math) that can later be
replaced/augmented by a model trained on real TTO/grant/licensing outcomes
(Priority 11). Every score is a pure function of structured inputs, so it is
reproducible and unit-testable.

Signals consumed (all optional; each missing signal falls back to a neutral
prior so the engine never crashes a report):
    approval_prob   float 0-1   PTRS-anchored FDA approval probability
    moat            float 0-1   competitive moat (panel score / 10)
    whitespace      float 0-1   IP/competitive openness (OPEN/ACTIVE/CROWDED)
    trl             int 1-9     Technology Readiness Level
    sbir_p1_ready   bool        meets TRL bar for SBIR Phase I
    sbir_awards     int         recent SBIR/STTR awards in the space
    som_usd         float       serviceable obtainable market (US)
    payer_barrier   str|None    key reimbursement barrier (text)
    modality        str         product_type / sub-expert id
    designations    list[str]   available expedited FDA designations
"""

from __future__ import annotations

import logging
import math
from typing import Optional

logger = logging.getLogger(__name__)

NEUTRAL = 0.5  # prior for any unknown signal


# ── Modality calibration tables ────────────────────────────────────────────────
# Rough base rates by product class, used as priors that the live signals adjust.
def _modality(product_type: str, sub_expert_id: str = "") -> str:
    s = f"{product_type} {sub_expert_id}".lower()
    if any(k in s for k in ("gene", "cell", "car-t", "car_t", "crispr", "aav")):
        return "gene_cell"
    if any(k in s for k in ("biologic", "antibody", "mab", "protein", "peptide", "adc")):
        return "biologic"
    if "vaccine" in s:
        return "vaccine"
    if any(k in s for k in ("device", "implant", "stent", "surgical", "instrument")):
        return "device"
    if any(k in s for k in ("diagnostic", "assay", "ivd", "test", "biomarker")):
        return "diagnostic"
    if any(k in s for k in ("software", "digital", "samd", "algorithm", "app")):
        return "digital"
    if any(k in s for k in ("antibiotic", "small_molecule", "small molecule", "drug", "molecule", "amr")):
        return "small_molecule"
    return "other"


#                        patent  license  spinout  acquire  sbir   reimburse
_MODALITY_PRIORS = {
    "small_molecule": (0.72,   0.78,    0.55,    0.72,    0.70,  0.65),
    "biologic":       (0.76,   0.80,    0.58,    0.78,    0.62,  0.60),
    "gene_cell":      (0.80,   0.72,    0.62,    0.70,    0.60,  0.45),
    "vaccine":        (0.70,   0.70,    0.50,    0.58,    0.72,  0.70),
    "device":         (0.62,   0.55,    0.60,    0.60,    0.72,  0.50),
    "diagnostic":     (0.60,   0.52,    0.58,    0.55,    0.74,  0.45),
    "digital":        (0.42,   0.45,    0.55,    0.45,    0.66,  0.40),
    "other":          (0.58,   0.58,    0.55,    0.58,    0.66,  0.55),
}
_PRIOR_KEYS = ("patent", "license", "spinout", "acquire", "sbir", "reimburse")

# Per-modality wording for the commercialization rationales: (readable label, IP noun,
# is_device_class). Device-class (device/diagnostic/digital) uses FDA CLEARANCE framing and
# non-"composition" IP language, so a SaMD/device assessment never reads like a drug.
_MODALITY_TEXT = {
    "small_molecule": ("small-molecule drug", "composition-of-matter and method-of-use claims", False),
    "biologic":       ("biologic",            "formulation and manufacturing (BLA) claims",      False),
    "gene_cell":      ("gene/cell therapy",   "vector, construct, and manufacturing claims",     False),
    "vaccine":        ("vaccine",             "antigen and platform claims",                     False),
    "device":         ("medical device",      "device design and method-of-use claims",          True),
    "diagnostic":     ("diagnostic",          "assay, biomarker, and method claims",             True),
    "digital":        ("AI/software (SaMD)",  "software, algorithm, and method claims",          True),
    "other":          ("product",             "the applicable IP claims",                        False),
}


def _clamp(x: float) -> float:
    return round(max(0.0, min(1.0, x)), 2)


def _market_score(som_usd: Optional[float]) -> float:
    """Log-scale SOM into 0-1: ~$1M -> 0.0, ~$1B -> 1.0."""
    if not som_usd or som_usd <= 0:
        return NEUTRAL
    return _clamp((math.log10(som_usd) - 6.0) / 3.0)


def _whitespace_from_signal(signal: Optional[str]) -> float:
    return {"open": 0.85, "active": 0.55, "crowded": 0.25}.get(
        (signal or "").strip().lower(), NEUTRAL)


# ── Core scorer (pure) ─────────────────────────────────────────────────────────

def score_commercialization(signals: dict) -> dict:
    """Compute the commercialization_scores block from structured signals."""
    modality = signals.get("modality") or "other"
    priors = dict(zip(_PRIOR_KEYS, _MODALITY_PRIORS.get(modality, _MODALITY_PRIORS["other"])))

    approval = signals.get("approval_prob")
    approval = NEUTRAL if approval is None else max(0.0, min(1.0, approval))
    moat = signals.get("moat")
    moat = NEUTRAL if moat is None else max(0.0, min(1.0, moat))
    whitespace = signals.get("whitespace")
    whitespace = NEUTRAL if whitespace is None else max(0.0, min(1.0, whitespace))
    trl = signals.get("trl") or 3
    trl_n = max(1, min(9, trl)) / 9.0
    market = _market_score(signals.get("som_usd"))
    designations = signals.get("designations") or []
    desig_factor = min(len(designations) / 3.0, 1.0)

    # SBIR is early-stage non-dilutive money: best fit at TRL ~2-4.
    trl_sbir_fit = _clamp(1.0 - abs((signals.get("trl") or 3) - 4) / 5.0)
    sbir_activity = min((signals.get("sbir_awards") or 0) / 10.0, 1.0)
    sbir_ready = 1.0 if signals.get("sbir_p1_ready") else 0.35

    # Reimbursement: modality prior nudged by approval confidence and payer barrier.
    payer_barrier = (signals.get("payer_barrier") or "").lower()
    severe_barrier = any(k in payer_barrier for k in
                         ("no code", "not reimbursed", "no reimbursement", "high price",
                          "budget", "cost-effective", "coverage gap", "out-of-pocket"))
    reimbursement = priors["reimburse"] + 0.10 * (approval - NEUTRAL)
    if severe_barrier:
        reimbursement -= 0.12

    scores = {
        "patentability":           _clamp(0.50 * priors["patent"] + 0.30 * whitespace + 0.20 * trl_n),
        "licensing_likelihood":    _clamp(0.30 * moat + 0.25 * approval + 0.20 * market
                                          + 0.15 * trl_n + 0.10 * priors["license"]),
        "spinout_likelihood":      _clamp(0.30 * market + 0.25 * moat + 0.20 * trl_n
                                          + 0.15 * whitespace + 0.10 * priors["spinout"]),
        "sbir_fit":                _clamp(0.40 * sbir_ready + 0.25 * trl_sbir_fit
                                          + 0.20 * sbir_activity + 0.15 * priors["sbir"]),
        "investor_attractiveness": _clamp(0.35 * market + 0.25 * approval + 0.20 * moat + 0.20 * trl_n),
        "regulatory_feasibility":  _clamp(0.80 * approval + 0.20 * desig_factor),
        "reimbursement_feasibility": _clamp(reimbursement),
        "acquisition_potential":   _clamp(0.30 * moat + 0.30 * market + 0.20 * approval + 0.20 * priors["acquire"]),
        "competitive_whitespace":  _clamp(0.70 * whitespace + 0.30 * moat),
    }

    # Overall priority — weighted blend of the decision-relevant dimensions.
    overall = (
        0.22 * scores["investor_attractiveness"]
        + 0.18 * scores["regulatory_feasibility"]
        + 0.15 * market
        + 0.12 * scores["patentability"]
        + 0.10 * scores["licensing_likelihood"]
        + 0.08 * scores["sbir_fit"]
        + 0.08 * scores["competitive_whitespace"]
        + 0.07 * scores["reimbursement_feasibility"]
    )
    scores["overall_priority"] = _clamp(overall)

    return {
        "commercialization_scores": scores,
        "score_rationales": build_rationales(signals, scores, market, whitespace),
        "top_drivers": _top_drivers(scores, market, whitespace),
        "recommendation": _recommendation(scores),
        "modality": modality,
        "method": "rules+calibrated_tables_v1",
    }


# ── Sourced, evidence-led rationale for every dimension ─────────────────────────
# Each score is paired with the real signals + sources that produced it, so the UI
# can lead with the evidence and treat the number as secondary (not a black box).

_SRC = {
    "ptrs":     "Historical FDA approval rates for this class & phase (PTRS calibration tables)",
    "moat":     "Competitive-moat assessment (expert panel, grounded in AUTM/BIO deal comps)",
    "patents":  "Recent US patent filings (Google Patents)",
    "trl":      "Technology Readiness Level assessment (NIH/BARDA framework)",
    "sbir":     "Recent NIH SBIR/STTR awards in this space (NIH Reporter)",
    "market":   "Bottom-up market sizing (CDC/SEER epidemiology + CMS pricing)",
    "modality": "Modality base rates (AUTM licensing surveys + FDA approval data)",
    "payer":    "Payer/reimbursement assessment (expert panel + CMS coverage data)",
}


def _band(v: float) -> str:
    return "STRONG" if v >= 0.66 else ("MODERATE" if v >= 0.45 else "WEAK")


def _ws_word(w: float) -> str:
    return "open" if w >= 0.66 else ("crowded" if w <= 0.34 else "moderately contested")


def build_rationales(signals: dict, scores: dict, market: float, whitespace: float) -> dict:
    """Per-dimension {label, drivers:[{fact, source}]} — the evidence behind each score."""
    _mkey = signals.get("modality") or "other"
    label, ip_noun, is_devclass = _MODALITY_TEXT.get(_mkey, _MODALITY_TEXT["other"])
    approval = signals.get("approval_prob")
    moat = signals.get("moat")
    trl = signals.get("trl")
    sbir_ready = signals.get("sbir_p1_ready")
    sbir_awards = signals.get("sbir_awards") or 0
    som = signals.get("som_usd")
    designations = signals.get("designations") or []
    payer = signals.get("payer_barrier")

    def d(fact, src):
        return {"fact": fact, "source": _SRC.get(src, src)}

    def dim(key, drivers):
        return {"label": _band(scores[key]), "score": scores[key],
                "drivers": [x for x in drivers if x]}

    reg = []
    if approval is not None:
        if is_devclass:
            reg.append(d(f"{approval*100:.0f}% FDA clearance likelihood (De Novo / 510(k)) for this {label} at this stage", "ptrs"))
        else:
            reg.append(d(f"{approval*100:.0f}% historical probability of approval for this {label} at this phase", "ptrs"))
    if designations:
        reg.append(d(f"Eligible expedited pathways: {', '.join(designations[:4])}", "ptrs"))

    sbir = []
    if sbir_ready and trl:
        sbir.append(d(f"Meets the TRL bar for SBIR Phase I (TRL {trl})", "trl"))
    if sbir_awards:
        sbir.append(d(f"{sbir_awards} recent NIH SBIR/STTR award(s) funding comparable work", "sbir"))
    sbir.append(d(f"{'Strong' if scores['sbir_fit'] >= 0.6 else 'Modest'} non-dilutive funding track record for a {label}", "modality"))

    ws = [d(f"IP/competitive landscape looks {_ws_word(whitespace)} based on recent filings", "patents")] if whitespace is not None else []

    _ip = ip_noun[0].upper() + ip_noun[1:]
    pat = list(ws) + [d(f"{_ip} are {'readily' if scores['patentability'] >= 0.6 else 'less reliably'} defensible", "modality")]

    inv = []
    if som:
        inv.append(d(f"~${som/1e6:.0f}M serviceable obtainable market (US)", "market"))
    if approval is not None:
        inv.append(d(f"{approval*100:.0f}% approval odds set the risk-adjusted value", "ptrs"))
    if moat is not None:
        inv.append(d(f"Competitive moat assessed {moat*10:.1f}/10 by the panel", "moat"))

    lic = []
    if moat is not None:
        lic.append(d(f"Competitive moat {moat*10:.1f}/10 (panel)", "moat"))
    if som:
        lic.append(d(f"~${som/1e6:.0f}M serviceable market", "market"))

    reimb = []
    if payer:
        reimb.append(d(f"Key payer barrier: {payer}", "payer"))
    reimb.append(d(
        (f"{label} reimbursement is institutional/coverage-driven (hospital budget, CPT/coverage) — base rate"
         if is_devclass else f"{label} reimbursement pathway base rate"), "modality"))

    return {
        "regulatory_feasibility":  dim("regulatory_feasibility", reg),
        "sbir_fit":                dim("sbir_fit", sbir),
        "competitive_whitespace":  dim("competitive_whitespace", ws),
        "patentability":           dim("patentability", pat),
        "investor_attractiveness": dim("investor_attractiveness", inv),
        "licensing_likelihood":    dim("licensing_likelihood", lic),
        "acquisition_potential":   dim("acquisition_potential", lic),
        "spinout_likelihood":      dim("spinout_likelihood", inv),
        "reimbursement_feasibility": dim("reimbursement_feasibility", reimb),
    }


# ── Drivers + recommendation ───────────────────────────────────────────────────

# label, positive-phrase, negative-phrase
_DRIVER_PHRASES = {
    "regulatory_feasibility": ("Favorable regulatory pathway (PTRS-anchored approval odds)",
                               "Low historical approval probability for this class/phase"),
    "competitive_whitespace": ("Open IP / competitive whitespace",
                               "Crowded patent & competitive landscape"),
    "sbir_fit":               ("Strong non-dilutive SBIR/STTR fit",
                               "Weak SBIR/STTR fit at current stage"),
    "investor_attractiveness":("Attractive venture profile",
                               "Limited venture appeal at current stage/market"),
    "patentability":          ("Strong patentability",
                               "Weak or uncertain patent position"),
    "reimbursement_feasibility":("Clear reimbursement pathway",
                                 "Uncertain reimbursement / payer pathway"),
    "licensing_likelihood":   ("Licensable to an established player",
                               "Limited near-term licensing appeal"),
    "acquisition_potential":  ("Credible acquisition exit",
                               "Limited acquisition appeal"),
}


def _top_drivers(scores: dict, market: float, whitespace: float) -> list[str]:
    """Surface the strongest positives and the most material risks."""
    drivers: list[str] = []
    # strongest positives
    for key, val in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        if key == "overall_priority":
            continue
        if val >= 0.65 and key in _DRIVER_PHRASES:
            drivers.append(_DRIVER_PHRASES[key][0])
        if len(drivers) >= 2:
            break
    if market >= 0.66:
        drivers.append("Large addressable market")
    # material risks
    risks: list[str] = []
    for key, val in sorted(scores.items(), key=lambda kv: kv[1]):
        if key == "overall_priority":
            continue
        if val <= 0.40 and key in _DRIVER_PHRASES:
            risks.append(_DRIVER_PHRASES[key][1])
        if len(risks) >= 2:
            break
    if market <= 0.34:
        risks.append("Limited market size")
    return drivers[:3] + risks[:2]


def _recommendation(s: dict) -> str:
    """Rule-based next-action, mirroring how a TTO analyst would triage."""
    sbir, inv = s["sbir_fit"], s["investor_attractiveness"]
    lic, spin = s["licensing_likelihood"], s["spinout_likelihood"]
    pat, white = s["patentability"], s["competitive_whitespace"]
    overall = s["overall_priority"]

    if overall < 0.40:
        return ("Deprioritize relative to the portfolio unless the key risks "
                "(regulatory odds, IP whitespace, or market size) can be materially de-risked.")

    # Primary action
    if sbir >= 0.65 and inv < 0.60:
        primary = "Pursue SBIR/STTR Phase I and file a provisional patent before investor outreach."
    elif inv >= 0.65 and spin >= lic:
        primary = "Strong venture profile — prepare a seed/Series A raise and form a NewCo; file IP first."
    elif lic >= 0.60 and lic >= spin:
        primary = "Best fit is licensing to an established player — prepare a non-confidential summary for outreach."
    else:
        primary = "Advance to a provisional patent and run targeted funder outreach matched to current TRL."

    # Guardrail
    if pat < 0.45 or white < 0.35:
        primary += " Validate freedom-to-operate / patentability before further spend."
    elif s["reimbursement_feasibility"] < 0.45:
        primary += " Build the reimbursement/coding strategy early — it is the main commercial risk."
    return primary


# ── Signal gathering from pipeline objects ─────────────────────────────────────

def gather_signals(
    *,
    product_type: str = "other",
    sub_expert_id: str = "",
    panel_result=None,
    patent_landscape: Optional[dict] = None,
    trl_result=None,
    deriv=None,
    sbir_awards: int = 0,
) -> dict:
    """Extract the scorer's structured inputs from in-flight pipeline objects.
    Everything is defensive — any missing/failed object degrades to a neutral prior."""
    signals: dict = {
        "modality": _modality(product_type, sub_expert_id),
        "sbir_awards": sbir_awards or 0,
    }

    reg = getattr(panel_result, "regulatory", None)
    if reg is not None:
        pct = getattr(reg, "approval_probability_pct", None)
        if pct is not None:
            signals["approval_prob"] = pct / 100.0
        signals["designations"] = getattr(reg, "available_designations", []) or []
    com = getattr(panel_result, "commercial", None)
    if com is not None:
        moat10 = getattr(com, "competitive_moat_score", None)
        if moat10 is not None:
            signals["moat"] = moat10 / 10.0
        signals["payer_barrier"] = getattr(com, "key_payer_barrier", None)

    if isinstance(patent_landscape, dict) and patent_landscape:
        signals["whitespace"] = _whitespace_from_signal(patent_landscape.get("activity_signal"))

    if trl_result is not None:
        signals["trl"] = getattr(trl_result, "trl_level", None)
        signals["sbir_p1_ready"] = bool(getattr(trl_result, "sbir_phase1_ready", False))

    if deriv is not None:
        signals["som_usd"] = getattr(deriv, "us_som_usd", None)
        signals["tam_usd"] = getattr(deriv, "us_tam_usd", None)

    return signals


def build_decision(**kwargs) -> dict:
    """Convenience: gather signals from pipeline objects and score in one call."""
    return score_commercialization(gather_signals(**kwargs))
