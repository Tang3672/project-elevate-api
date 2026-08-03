"""
Assumption Ledger Service  (Part E)
=====================================
Builds an AssumptionLedger from a MarketSizingDerivation and stamps it onto PIReport.
Also handles user override capture and diff view generation.

Design:
  - An AssumptionLedger is a flat list of Assumption objects extracted from
    MarketSizingDerivation.steps and key_assumptions.
  - Each assumption has a source (llm_generated | retrieved | fallback_default),
    a value, a unit, and a sensitivity_rank.
  - The ledger is stored on PIReport.assumption_ledger so any endpoint can read it.
  - User overrides are captured via PATCH /api/v1/pi-report/{job_id}/assumptions/{key}
    and stored back onto the job's report dict in the job store.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from app.models.alignment import Assumption, AssumptionLedger, AssumptionSource

logger = logging.getLogger(__name__)


# ── Value extractor helpers ───────────────────────────────────────────────────

def _extract_usd(text: str) -> Optional[float]:
    """
    Extract a dollar value from a DerivationStep notes/explanation string.
    Handles $1.2B, $450M, $12,000, etc.
    Returns None if no dollar value found.
    """
    m = re.search(
        r"\$\s*([\d,]+(?:\.\d+)?)\s*([BMK])?",
        text or "",
        re.I,
    )
    if not m:
        return None
    val = float(m.group(1).replace(",", ""))
    suffix = (m.group(2) or "").upper()
    if suffix == "B":
        val *= 1e9
    elif suffix == "M":
        val *= 1e6
    elif suffix == "K":
        val *= 1e3
    return val


def _extract_count(text: str) -> Optional[float]:
    """Extract a plain integer count (e.g. '14,000 labs') from text."""
    m = re.search(r"\b([\d,]+)\s*(?:labs?|facilities|patients?|sites?|PIs?|centers?)\b", text or "", re.I)
    if m:
        return float(m.group(1).replace(",", ""))
    return None


# ── Ledger builder ────────────────────────────────────────────────────────────

def build_ledger_from_derivation(
    deriv,
    generated_at: Optional[str] = None,
) -> AssumptionLedger:
    """
    Build an AssumptionLedger from a MarketSizingDerivation object.
    Extracts top-level figures + DerivationStep assumptions.

    deriv: MarketSizingDerivation dataclass instance
    """
    assumptions: list[Assumption] = []
    now_iso = generated_at or datetime.now(timezone.utc).isoformat()

    # ── Top-level TAM/SAM/SOM ────────────────────────────────────────────────
    tam = float(getattr(deriv, "us_tam_usd", 0) or 0)
    sam = float(getattr(deriv, "us_sam_usd", 0) or 0)
    som = float(getattr(deriv, "us_som_usd", 0) or 0)

    if tam > 0:
        assumptions.append(Assumption(
            key="us_tam_usd",
            label="Total Addressable Market (US, annual)",
            value=tam,
            unit="USD",
            source=AssumptionSource.RETRIEVED,
            source_detail=f"Bottom-up derivation ({getattr(deriv, 'formula_name', '')})",
            confidence="medium",
            sensitivity_rank=1,
        ))
    if sam > 0:
        assumptions.append(Assumption(
            key="us_sam_usd",
            label="Serviceable Addressable Market (US, annual)",
            value=sam,
            unit="USD",
            source=AssumptionSource.RETRIEVED,
            source_detail=f"Bottom-up derivation ({getattr(deriv, 'formula_name', '')})",
            confidence="medium",
            sensitivity_rank=2,
        ))
    if som > 0:
        assumptions.append(Assumption(
            key="us_som_usd",
            label="Serviceable Obtainable Market (Year-1, US)",
            value=som,
            unit="USD",
            source=AssumptionSource.RETRIEVED,
            source_detail=f"Bottom-up derivation ({getattr(deriv, 'formula_name', '')})",
            confidence="low",
            sensitivity_rank=3,
        ))

    # ── Per-step assumptions from DerivationStep.assumptions list ───────────
    _seen_keys: set[str] = set()
    for i, step in enumerate(getattr(deriv, "steps", []) or [], start=1):
        label = getattr(step, "label", f"Step {i}")
        value_num = getattr(step, "value", None)
        unit_str  = getattr(step, "unit", "")
        step_assumptions = getattr(step, "assumptions", []) or []
        data_source = getattr(step, "data_source", "") or ""

        # The step itself is an assumption
        if value_num is not None and value_num != 0:
            _key = f"step_{i}_{label[:20].lower().replace(' ', '_').replace('/', '_')}"
            if _key not in _seen_keys:
                _seen_keys.add(_key)
                src = (AssumptionSource.RETRIEVED
                       if data_source and "Computed" not in data_source
                       else AssumptionSource.LLM_GENERATED)
                assumptions.append(Assumption(
                    key=_key,
                    label=label,
                    value=float(value_num),
                    unit=unit_str or "USD",
                    source=src,
                    source_detail=data_source or None,
                    sensitivity_rank=3 + i,
                ))

    # ── Key textual assumptions from key_assumptions list ────────────────────
    for j, ka in enumerate(getattr(deriv, "key_assumptions", []) or [], start=1):
        if not ka:
            continue
        # Try to extract a numeric value; else store as a flag assumption (value=1)
        usd_val = _extract_usd(ka)
        cnt_val = _extract_count(ka)
        val = usd_val or cnt_val or 1.0
        unit = "USD" if usd_val else ("count" if cnt_val else "flag")
        _kkey = f"key_assumption_{j}"
        assumptions.append(Assumption(
            key=_kkey,
            label=ka[:120],
            value=val,
            unit=unit,
            source=AssumptionSource.LLM_GENERATED,
            confidence="low",
            note=ka if len(ka) > 120 else None,
        ))

    return AssumptionLedger(
        assumptions=assumptions,
        generated_at=now_iso,
        last_modified=None,
        override_count=0,
    )


# ── Override capture ──────────────────────────────────────────────────────────

def apply_override(
    ledger: AssumptionLedger,
    key: str,
    new_value: float,
    note: Optional[str] = None,
) -> tuple[AssumptionLedger, bool]:
    """
    Apply a user override to a specific assumption by key.
    Returns (updated_ledger, found).
    The original value is preserved in Assumption.override_value.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    for assumption in ledger.assumptions:
        if assumption.key == key:
            assumption.override_value = assumption.value
            assumption.value = new_value
            assumption.source = AssumptionSource.USER_OVERRIDE
            assumption.overridden_at = now_iso
            if note:
                assumption.note = note
            ledger.override_count += 1
            ledger.last_modified = now_iso
            # E.4: stamp version hash on every mutation so each ledger state is identifiable
            _payload = json.dumps(
                [(a.key, a.value, a.override_value) for a in ledger.assumptions],
                sort_keys=True,
            ).encode()
            ledger.version_hash = hashlib.sha256(_payload).hexdigest()[:16]
            return ledger, True
    return ledger, False


# ── Diff view ────────────────────────────────────────────────────────────────

def ledger_diff(ledger: AssumptionLedger) -> list[dict]:
    """
    Return a list of dicts describing only the user-overridden assumptions,
    showing original vs. new values. Used by the diff view endpoint.
    """
    diffs = []
    for a in ledger.assumptions:
        if a.source == AssumptionSource.USER_OVERRIDE and a.override_value is not None:
            pct = ((a.value - a.override_value) / a.override_value * 100
                   if a.override_value != 0 else 0)
            diffs.append({
                "key":             a.key,
                "label":           a.label,
                "original_value":  a.override_value,
                "new_value":       a.value,
                "unit":            a.unit,
                "change_pct":      round(pct, 1),
                "overridden_at":   a.overridden_at,
                "note":            a.note,
            })
    return diffs
