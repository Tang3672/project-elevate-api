"""
PDF Renderer  (P2 — F-01 through F-09)
=======================================
Converts a PIReport dict into a print-ready HTML document, then optionally
renders it to PDF bytes via headless Chromium (playwright).

Defects addressed:
  F-01  Title from dedicated product_name field, not negated taxonomy
  F-02  Expert routing machinery hidden from user-visible output
  F-03  No character caps; word-boundary truncation utility only
  F-04  URLs never broken mid-token; §8 only, with word-break:break-all CSS
  F-05  Citations missing URLs get "[no public URL available]" marker
  F-06  Duplicate step-number prefix stripped from content; empty labels cleaned
  F-07  Full header page 1 only; CSS @page running head p2+; footer once, final page
  F-08  Tabular data rendered as <table> elements, not bullet lists
  F-09  Type scale, humanist serif, 70ch measure, tabular figures, one accent
"""

from __future__ import annotations

import html
import logging
import re
from datetime import date
from typing import Optional

logger = logging.getLogger(__name__)

# ── F-01: product name derivation ────────────────────────────────────────────

def derive_product_name(report: dict) -> str:
    """
    Returns the product name for the report title.
    Priority: report.product_name → first segment of idea_submitted → fallback.
    Strips any taxonomy/archetype prefix that was wrongly used as a title.
    """
    if report.get("product_name"):
        return report["product_name"].strip()
    idea = report.get("idea_submitted", "").strip()
    if ":" in idea:
        candidate = idea.split(":")[0].strip()
        # Accept if it's a short proper noun phrase (not a sentence fragment)
        candidate = strip_negation(candidate)
        if candidate and 2 <= len(candidate) <= 50 and candidate[0].isupper():
            return candidate
    # First 3 words of idea, after stripping any leading negation
    cleaned_idea = strip_negation(idea)
    words = (cleaned_idea or idea).split()[:3]
    return " ".join(words) if words else "Medlevate Report"


def derive_domain_label(report: dict) -> str:
    """Human-readable domain label from archetype/expert_domain."""
    _label_map = {
        "research_tool_non_clinical":    "Research Data Infrastructure",
        "research_infrastructure_saas":  "Research Infrastructure",
        "drug_amr":                      "Antimicrobial Drug",
        "drug_oncology":                 "Oncology Drug",
        "drug_cns":                      "CNS Drug",
        "drug_cardiology":               "Cardiovascular Drug",
        "drug_rare_disease":             "Rare Disease Drug",
        "drug_metabolic":                "Metabolic Disease Drug",
        "drug_immunology":               "Immunology Drug",
        "device_cardiovascular":         "Cardiovascular Device",
        "device_neurology":              "Neurology Device",
        "device_metabolic":              "Metabolic Device",
        "digital_cds":                   "Clinical Decision Support",
        "digital_rpm":                   "Remote Patient Monitoring",
        "digital_therapeutic":           "Digital Therapeutic",
        "diagnostic_oncology":           "Oncology Diagnostic",
        "diagnostic_cardiovascular":     "Cardiovascular Diagnostic",
        "samd_clinical":                 "Software as a Medical Device",
    }
    sid = (report.get("expert_domain") or "").lower()
    return _label_map.get(sid, sid.replace("_", " ").title() if sid else "Commercial Intelligence")


def derive_report_date(report: dict, report_date: str = "") -> str:
    """Returns formatted date string for the meta line."""
    if report_date:
        return report_date
    gen = report.get("generated_at")
    if gen:
        try:
            from datetime import datetime
            if isinstance(gen, str):
                d = datetime.fromisoformat(gen.replace("Z", "+00:00"))
            elif isinstance(gen, datetime):
                d = gen
            else:
                d = datetime.utcnow()
            return d.strftime("%B %Y")
        except Exception:
            pass
    return date.today().strftime("%B %Y")


def derive_filename(product_name: str, report_date: str = "") -> str:
    """F-01: hublink-commercial-intelligence-2026-07-29.pdf"""
    slug = re.sub(r"[^a-z0-9]+", "-", product_name.lower()).strip("-")
    d = report_date or date.today().isoformat()
    return f"{slug}-commercial-intelligence-{d}.pdf"


# ── C.3: negation suppression ────────────────────────────────────────────────

_NEGATION_PREFIXES = re.compile(
    r"^\s*(Not applicable|Not disease-specific|Not disease specific|N/A\s*[—–\-]|"
    r"No clinical indication|Non-clinical|Not a clinical|Not FDA-regulated)\s*[—–\-:,]?\s*",
    re.I,
)

def strip_negation(text: str) -> str:
    """C.3: Remove negation prefixes from titles and headings before rendering.
    Sections that don't apply are suppressed entirely; this is a safety net for
    prose that slipped through with a negation as a leading phrase.
    """
    if not text:
        return text
    cleaned = _NEGATION_PREFIXES.sub("", text).strip()
    # If stripping left a lone period or connector, return empty
    if cleaned in {".", "-", "—", "–", ",", ":"}:
        return ""
    return cleaned


# ── F-03: word-boundary truncation ───────────────────────────────────────────

def truncate_at_word(text: str, max_chars: int, ellipsis: str = "…") -> str:
    """
    Truncate at a word boundary (never mid-token).
    Only call this when content must be bounded before rendering — the renderer
    itself never applies a character cap.
    """
    if not text or len(text) <= max_chars:
        return text
    cut = text[:max_chars].rsplit(" ", 1)[0].rstrip(",:;")
    return cut + ellipsis


# ── F-06: step-label deduplication ───────────────────────────────────────────

def clean_step_label(label: str, content: str) -> tuple[str, str]:
    """
    F-06: If content starts with the same prefix as label, strip it.
    "Step 1", "Step 1: Addressable hospital..." → "Step 1", "Addressable hospital..."
    "• - $75,000/site/yr" (empty label) → "", "$75,000/site/yr"
    """
    label = (label or "").strip()
    content = (content or "").strip()
    if label and content:
        # Strip duplicate label prefix from content (case-insensitive)
        esc = re.escape(label)
        content = re.sub(r"^" + esc + r"\s*[:\-–—·]\s*", "", content, flags=re.I)
    # Clean empty-label separator patterns like "• - " or "· —"
    if not label or label in {"-", "•", "·", "–", "—"}:
        label = ""
        content = re.sub(r"^[-–—·•]\s*", "", content)
    return label, content


_LIST_ITEM_BULLET_RE = re.compile(r"^[\s]*[•·\-–—]\s*[-–—]?\s*", re.UNICODE)


def clean_list_item(s: str) -> str:
    """
    F-06: Strip leading bullet/dash prefixes from a plain-string list item.
    "• - $15,000/site/yr"  → "$15,000/site/yr"
    "- Consider filing…"   → "Consider filing…"
    Leaves normal prose untouched.
    """
    if not s:
        return s
    return _LIST_ITEM_BULLET_RE.sub("", s).strip()


# ── F-05: citation URL validation ─────────────────────────────────────────────

_NO_URL_MARKER = "[no public URL available]"
_GENERIC_SEARCH_PATTERNS = [
    r"google\.com/search",
    r"bing\.com/search",
    r"pubmed\.ncbi\.nlm\.nih\.gov/search",
    r"scholar\.google",
]


def validate_citation_url(url: str) -> tuple[str, bool]:
    """
    F-05: Returns (display_url, is_valid).
    Generic search pages → is_valid=False.
    Empty → is_valid=False.
    """
    if not url or not url.strip():
        return _NO_URL_MARKER, False
    url = url.strip()
    if any(re.search(p, url, re.I) for p in _GENERIC_SEARCH_PATTERNS):
        return _NO_URL_MARKER, False
    return url, True


# ── HTML escaping helper ──────────────────────────────────────────────────────

def _e(text) -> str:
    return html.escape(str(text or ""), quote=False)


def _link(url: str, text: str) -> str:
    """Render a hyperlink with F-04-safe URL (no whitespace injected)."""
    url = (url or "").strip()
    if not url:
        return _e(text)
    return f'<a href="{_e(url)}">{_e(text)}</a>'


def _build_toc(entries: list[tuple[bool, str, str]]) -> str:
    """
    G.11: Build TOC with sequential numbers that reflect only present sections.
    entries = [(is_present, anchor, label), ...].
    Citations always get § (not a number) and are appended unconditionally if present.
    """
    lines = []
    n = 0
    for present, anchor, label in entries:
        if not present:
            continue
        if anchor == "s-citations":
            lines.append(f'      <li><span class="toc-num">§</span><a href="#{anchor}">{label}</a></li>')
        else:
            n += 1
            lines.append(f'      <li><span class="toc-num">§{n}</span><a href="#{anchor}">{label}</a></li>')
    return "\n".join(lines)


# ── Section renderers (F-08: tables for structured data) ─────────────────────

def _render_market_sizing(ms: dict) -> str:
    if not ms:
        return ""
    steps = ms.get("steps", [])
    formula = _e(ms.get("formula", ""))
    tam = _e(ms.get("total_addressable_market_usd", ""))
    sam = _e(ms.get("serviceable_market_usd", ""))
    note = _e(ms.get("methodology_note", ""))

    rows = ""
    for s in steps:
        label, content = clean_step_label(s.get("label", ""), s.get("notes", ""))
        src_url, _ = validate_citation_url(s.get("source_url", ""))
        src_text = _e(s.get("source", ""))
        src_display = _link(s.get("source_url", ""), src_text) if s.get("source_url") else _e(src_text)
        rows += f"""<tr>
          <td class="col-label">{_e(label or s.get("label",""))}</td>
          <td class="num">{_e(s.get("value",""))}</td>
          <td>{_e(s.get("unit",""))}</td>
          <td>{src_display}</td>
          <td class="note">{_e(content or s.get("notes",""))}</td>
        </tr>"""

    tam_fmt = f"${float(tam)/1e9:.1f}B" if tam else ""
    sam_fmt = f"${float(sam)/1e6:.0f}M" if sam else ""
    try:
        if tam:
            tam_fmt = f"${float(tam)/1e9:.1f}B" if float(tam) >= 1e9 else f"${float(tam)/1e6:.0f}M"
        if sam:
            sam_fmt = f"${float(sam)/1e6:.0f}M"
    except (ValueError, TypeError):
        pass

    return f"""
<div class="section" id="s-market">
  <h2><span class="sec-num"></span> Market Sizing</h2>
  <table class="data-table">
    <thead><tr>
      <th>Step</th><th class="num">Value</th><th>Unit</th>
      <th>Source</th><th>Notes</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>
  {f'<p class="formula"><strong>Formula:</strong> {formula}</p>' if formula else ""}
  <dl class="summary-row">
    {f'<div><dt>Total Addressable Market</dt><dd class="num big">{tam_fmt}</dd></div>' if tam_fmt else ""}
    {f'<div><dt>Serviceable Market</dt><dd class="num big">{sam_fmt}</dd></div>' if sam_fmt else ""}
  </dl>
  {f'<p class="methodology">{note}</p>' if note else ""}
</div>"""


def _render_axis_decisions(axis_decisions: dict) -> str:
    """Render C.1/C.2 segmentation axis selection/rejection table.

    Outputs two blocks:
    - Selected axes (used to build the market funnel)
    - Considered and excluded axes (with rejection reasons)
    """
    if not axis_decisions:
        return ""
    selected = axis_decisions.get("selected", [])
    rejected = axis_decisions.get("rejected", [])
    if not selected and not rejected:
        return ""

    sel_rows = ""
    for ax in selected:
        lift = ax.get("est_lift")
        lift_str = f"{lift:.0%}" if lift else "—"
        sel_rows += f"""<tr>
          <td>{_e(ax.get("label",""))}</td>
          <td><span class="family-tag">{_e(ax.get("family","").replace("_"," "))}</span></td>
          <td class="num">{lift_str}</td>
        </tr>"""

    rej_rows = ""
    for ax in rejected:
        if not ax.get("reason"):
            continue
        rej_rows += f"""<tr>
          <td>{_e(ax.get("label",""))}</td>
          <td><span class="family-tag">{_e(ax.get("family","").replace("_"," "))}</span></td>
          <td class="note">{_e(ax.get("reason",""))}</td>
        </tr>"""

    sel_block = f"""
<h3>Segmentation axes selected ({len(selected)})</h3>
<table class="data-table">
  <thead><tr><th>Axis</th><th>Family</th><th class="num">Typical variance explained</th></tr></thead>
  <tbody>{sel_rows}</tbody>
</table>""" if sel_rows else ""

    rej_block = f"""
<h3>Considered and excluded ({len([r for r in rejected if r.get("reason")])})</h3>
<table class="data-table">
  <thead><tr><th>Axis</th><th>Family</th><th>Reason excluded</th></tr></thead>
  <tbody>{rej_rows}</tbody>
</table>""" if rej_rows else ""

    return f"""
<div class="section" id="s-axis-decisions">
  <h2>Segmentation Methodology</h2>
  <p class="methodology">The following axes were evaluated for this product's buyer model.
  Axes are selected based on the buyer type, product domain, and available data sources.</p>
  {sel_block}
  {rej_block}
</div>"""


def _render_regulatory_pathway(rp: dict) -> str:
    if not rp:
        return ""
    pathway = _e(rp.get("recommended_pathway", ""))
    rationale = _e(rp.get("pathway_rationale", ""))
    timeline = _e(rp.get("total_timeline_estimate", ""))
    cost = _e(rp.get("total_cost_estimate", ""))
    frictions = rp.get("key_friction_points", [])
    loopholes = rp.get("loopholes_and_strategies", [])

    desig_rows = ""
    for d in rp.get("designations", []):
        src_link = _link(d.get("source_url", ""), d.get("source", "")) if d.get("source_url") else _e(d.get("source", ""))
        desig_rows += f"""<tr>
          <td><strong>{_e(d.get("name",""))}</strong></td>
          <td>{_e(d.get("benefit",""))}</td>
          <td>{_e(d.get("timeline",""))}</td>
          <td>{_e(d.get("eligibility",""))}</td>
          <td>{src_link}</td>
        </tr>"""

    trial_rows = ""
    for t in rp.get("clinical_trial_requirements", []):
        trial_rows += f"""<tr>
          <td>{_e(t.get("phase",""))}</td>
          <td class="num">{_e(t.get("patient_count",""))}</td>
          <td>{_e(t.get("duration",""))}</td>
          <td class="num">{_e(t.get("estimated_cost",""))}</td>
          <td>{_e(t.get("success_probability",""))}</td>
        </tr>"""

    friction_html = "".join(f"<li>{_e(clean_list_item(f))}</li>" for f in frictions)
    loop_html = "".join(f"<li>{_e(clean_list_item(l))}</li>" for l in loopholes)

    return f"""
<div class="section" id="s-regulatory">
  <h2><span class="sec-num"></span> Regulatory Pathway</h2>
  <p><strong>Recommended pathway:</strong> {pathway}</p>
  {f'<p>{rationale}</p>' if rationale else ""}
  <dl class="summary-row">
    {f'<div><dt>Timeline</dt><dd>{timeline}</dd></div>' if timeline else ""}
    {f'<div><dt>Estimated Cost</dt><dd class="num">{cost}</dd></div>' if cost else ""}
  </dl>
  {f'<h3>Available Designations</h3><table class="data-table"><thead><tr><th>Designation</th><th>Benefit</th><th>Timeline</th><th>Eligibility</th><th>Source</th></tr></thead><tbody>{desig_rows}</tbody></table>' if desig_rows else ""}
  {f'<h3>Clinical Trial Requirements</h3><table class="data-table"><thead><tr><th>Phase</th><th>Patients</th><th>Duration</th><th>Est. Cost</th><th>P(Success)</th></tr></thead><tbody>{trial_rows}</tbody></table>' if trial_rows else ""}
  {f'<h3>Key Friction Points</h3><ul>{friction_html}</ul>' if friction_html else ""}
  {f'<h3>Strategies &amp; Loopholes</h3><ul>{loop_html}</ul>' if loop_html else ""}
</div>"""


def _render_market_access(ma: dict) -> str:
    if not ma:
        return ""
    channel = _e(ma.get("primary_channel", ""))
    reimb = _e(ma.get("reimbursement_pathway", ""))
    first_step = _e(ma.get("first_commercial_step", ""))
    kols = ma.get("key_opinion_leaders", [])
    intl = ma.get("international_opportunities", [])

    seg_rows = ""
    for seg in ma.get("buyer_segments", []):
        src_link = _link(seg.get("source_url", ""), seg.get("source", "")) if seg.get("source_url") else _e(seg.get("source", ""))
        seg_rows += f"""<tr>
          <td><strong>{_e(seg.get("segment_name",""))}</strong></td>
          <td class="num">{_e(seg.get("buyer_count",""))}</td>
          <td>{_e(seg.get("decision_maker",""))}</td>
          <td class="num">{_e(seg.get("price_per_unit",""))}</td>
          <td>{_e(seg.get("access_mechanism",""))}</td>
          <td>{_e(seg.get("timeline_to_access",""))}</td>
          <td>{src_link}</td>
        </tr>"""

    kol_html = "".join(f"<li>{_e(clean_list_item(k) if isinstance(k, str) else str(k))}</li>" for k in kols[:10])
    intl_html = "".join(f"<li>{_e(clean_list_item(i))}</li>" for i in intl)

    return f"""
<div class="section" id="s-access">
  <h2><span class="sec-num"></span> Market Access &amp; Commercial Strategy</h2>
  {f'<p><strong>Primary channel:</strong> {channel}</p>' if channel else ""}
  {f'<p><strong>Reimbursement pathway:</strong> {reimb}</p>' if reimb else ""}
  {f'<p><strong>First commercial step:</strong> {first_step}</p>' if first_step else ""}
  {f'<h3>Buyer Segments</h3><table class="data-table"><thead><tr><th>Segment</th><th>Count</th><th>Decision-maker</th><th>Price / Unit</th><th>Access</th><th>Timeline</th><th>Source</th></tr></thead><tbody>{seg_rows}</tbody></table>' if seg_rows else ""}
  {f'<h3>Key Opinion Leaders</h3><ul class="kol-list">{kol_html}</ul>' if kol_html else ""}
  {f'<h3>International Opportunities</h3><ul>{intl_html}</ul>' if intl_html else ""}
</div>"""


def _render_competitive_landscape(ci: dict) -> str:
    if not ci:
        return ""
    from app.services.competitor_schema import normalize_landscape

    # B-05: normalize to unified schema — resolves key aliases and fills missing fields
    ci = normalize_landscape(ci)
    competitors = ci.get("competitors", [])
    trials = (ci.get("competitor_trials") or {}).get("trials", [])
    honest_empty = _e(ci.get("honest_empty_state", ""))

    # Detect corpus: research-tool landscape has no stage/company fields
    is_research_tool = ci.get("corpus", "").startswith("research_tool") or (
        competitors and not competitors[0].get("company")
    )

    comp_rows = ""
    if is_research_tool:
        for c in competitors:
            role = "Incumbent" if c.get("incumbent") else "Challenger"
            key_diff = _e(
                c.get("overlap") or c.get("key_differentiator") or c.get("description") or ""
            )
            win = _e(c.get("where_you_win") or "")
            lose = _e(c.get("where_you_lose") or "")
            switch = _e(c.get("switching_cost") or "")
            price = _e(c.get("price_point") or "")
            comp_rows += f"""<tr>
              <td><strong>{_e(c.get("name",""))}</strong><br>
                  <span class="sec-note">{_e(c.get("category",""))}</span></td>
              <td>{key_diff}</td>
              <td class="pos">{win}</td>
              <td class="neg">{lose}</td>
              <td>{switch}</td>
              <td>{price}</td>
              <td>{role}</td>
            </tr>"""
        header = "<tr><th>Product</th><th>Overlap</th><th>Where You Win</th><th>Where You Lose</th><th>Switching Cost</th><th>Price</th><th>Role</th></tr>"
    else:
        for c in competitors:
            adv = "; ".join(c.get("advantages") or [])
            vuln = "; ".join(c.get("vulnerabilities") or [])
            comp_rows += f"""<tr>
              <td><strong>{_e(c.get("name",""))}</strong>
                  {f"({_e(c.get('brand_name',''))})" if c.get("brand_name") else ""}</td>
              <td>{_e(c.get("company",""))}</td>
              <td>{_e(c.get("stage",""))}</td>
              <td>{_e(c.get("route",""))}</td>
              <td>{_e(adv)}</td>
              <td>{_e(vuln)}</td>
            </tr>"""
        header = "<tr><th>Product</th><th>Company</th><th>Stage</th><th>Route</th><th>Advantages</th><th>Vulnerabilities</th></tr>"

    trial_rows = ""
    for t in trials[:8]:
        trial_rows += f"""<tr>
          <td>{_e(t.get("nct_id",""))}</td>
          <td>{_e((t.get("title") or "")[:80])}</td>
          <td>{_e(t.get("status",""))}</td>
          <td>{_e(t.get("sponsor",""))}</td>
        </tr>"""

    return f"""
<div class="section" id="s-competitive">
  <h2><span class="sec-num"></span> Competitive Landscape</h2>
  {f'<p class="honest-empty">{honest_empty}</p>' if honest_empty else ""}
  {f'<table class="data-table"><thead>{header}</thead><tbody>{comp_rows}</tbody></table>' if comp_rows else ""}
  {f'<h3>Active Clinical Trials</h3><table class="data-table"><thead><tr><th>NCT ID</th><th>Title</th><th>Status</th><th>Sponsor</th></tr></thead><tbody>{trial_rows}</tbody></table>' if trial_rows else ""}
</div>"""


def _render_p1_sections(report: dict) -> str:
    out = ""

    # S-02 value driver ranking
    vdr = report.get("value_driver_ranking", [])
    if vdr:
        rows = ""
        for r in vdr:
            rows += f"""<tr>
              <td><strong>{_e(r.get("driver",""))}</strong></td>
              <td class="num">{_e(r.get("relative_importance","") or r.get("rank",""))}</td>
              <td>{_e(r.get("product_implication","") or r.get("rationale",""))}</td>
            </tr>"""
        out += f"""
<div class="section" id="s-value-drivers">
  <h2><span class="sec-num"></span> Value Driver Ranking</h2>
  <table class="data-table">
    <thead><tr><th>Driver</th><th>Importance</th><th>Product Implication</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""

    # S-03 segment fit table
    sft = report.get("segment_fit_table", [])
    if sft:
        rows = ""
        for r in sft:
            posture = _e(r.get("fit","") or r.get("posture",""))
            is_nontarget = "Explicit non-target" in posture or "non-target" in posture.lower()
            row_class = ' class="nontarget"' if is_nontarget else ""
            rows += f"""<tr{row_class}>
              <td><strong>{_e(r.get("segment","") or r.get("segment_name",""))}</strong></td>
              <td>{posture}</td>
              <td>{_e(r.get("rationale","") or r.get("reason",""))}</td>
            </tr>"""
        out += f"""
<div class="section" id="s-segments">
  <h2><span class="sec-num"></span> Segment Fit</h2>
  <table class="data-table">
    <thead><tr><th>Segment</th><th>Fit / Posture</th><th>Rationale</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""

    # S-04 feature investment posture
    fip = report.get("feature_investment_posture", [])
    if fip:
        rows = ""
        for r in fip:
            posture = _e(r.get("posture",""))
            is_exclude = posture.lower() == "exclude"
            row_class = ' class="exclude"' if is_exclude else ""
            rows += f"""<tr{row_class}>
              <td><strong>{_e(r.get("feature_area","") or r.get("feature",""))}</strong></td>
              <td>{posture}</td>
              <td>{_e(r.get("rationale",""))}</td>
            </tr>"""
        out += f"""
<div class="section" id="s-features">
  <h2><span class="sec-num"></span> Feature Investment Posture</h2>
  <table class="data-table">
    <thead><tr><th>Feature Area</th><th>Posture</th><th>Rationale</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <p class="table-note">Rows marked <em>Exclude</em> represent deliberate non-investment decisions.</p>
</div>"""

    # S-05 pricing model analysis
    pma = report.get("pricing_model_analysis") or {}
    if pma:
        model_rows = ""
        for m in pma.get("model_comparison", []):
            stance = _e(m.get("strategic_stance",""))
            is_rec = stance.lower() == "recommended"
            row_class = ' class="recommended"' if is_rec else ""
            model_rows += f"""<tr{row_class}>
              <td><strong>{_e(m.get("pricing_model",""))}</strong></td>
              <td>{_e(m.get("user_appeal",""))}</td>
              <td>{_e(m.get("business_sustainability",""))}</td>
              <td>{stance}</td>
            </tr>"""
        ctx_rows = ""
        for c in pma.get("contextual_analysis", []):
            ctx_rows += f"""<tr>
              <td>{_e(c.get("context",""))}</td>
              <td>{_e(c.get("why_this_model_works",""))}</td>
              <td>{_e(c.get("structural_risk",""))}</td>
            </tr>"""
        out += f"""
<div class="section" id="s-pricing">
  <h2><span class="sec-num"></span> Pricing Model Analysis</h2>
  {f'<table class="data-table"><thead><tr><th>Model</th><th>User Appeal</th><th>Sustainability</th><th>Stance</th></tr></thead><tbody>{model_rows}</tbody></table>' if model_rows else ""}
  {f'<h3>Contextual Analysis</h3><table class="data-table"><thead><tr><th>Context</th><th>Why It Works</th><th>Structural Risk</th></tr></thead><tbody>{ctx_rows}</tbody></table>' if ctx_rows else ""}
</div>"""

    # S-07 positioning statement
    ps = report.get("positioning_statement")
    if ps:
        out += f"""
<div class="section" id="s-positioning">
  <h2><span class="sec-num"></span> Positioning Statement</h2>
  <blockquote class="positioning">{_e(ps)}</blockquote>
</div>"""

    # S-08 strategic risks
    sr = report.get("strategic_risks", [])
    if sr:
        risks_html = "".join(f"<li>{_e(clean_list_item(r))}</li>" for r in sr)
        out += f"""
<div class="section" id="s-risks">
  <h2><span class="sec-num"></span> Strategic Risks</h2>
  <ul class="risk-list">{risks_html}</ul>
</div>"""

    # S-09 guiding question
    gq = report.get("guiding_question")
    if gq:
        out += f"""
<div class="section" id="s-guiding">
  <h2><span class="sec-num"></span> Guiding Question</h2>
  <p class="guiding-question">{_e(gq)}</p>
</div>"""

    # S-06 adversarial review
    adv = report.get("adversarial_review", [])
    if adv:
        adv_rows = ""
        for item in adv:
            adv_rows += f"""<tr>
              <td>{_e(item.get("recommendation",""))}</td>
              <td>{_e(item.get("supporting_case",""))}</td>
              <td class="risk-cell">{_e(item.get("structural_risk",""))}</td>
              <td>{_e(item.get("disconfirming_evidence",""))}</td>
              <td>{_e(item.get("what_would_change_this",""))}</td>
            </tr>"""
        out += f"""
<div class="section" id="s-adversarial">
  <h2><span class="sec-num"></span> Adversarial Review</h2>
  <p class="section-note">Independent critic pass — each recommendation evaluated for structural risk and disconfirming evidence.</p>
  <table class="data-table adversarial-table">
    <thead><tr>
      <th>Recommendation</th><th>Supporting Case</th>
      <th>Structural Risk</th><th>Disconfirming Evidence</th>
      <th>What Would Change This</th>
    </tr></thead>
    <tbody>{adv_rows}</tbody>
  </table>
</div>"""

    return out


def _render_citations(citations: list) -> str:
    if not citations:
        return ""
    rows = ""
    for c in citations:
        num = _e(c.get("number", c.get("num", "")))
        name = _e(c.get("name", c.get("title", "")))
        publisher = _e(c.get("publisher", ""))
        accessed = _e(c.get("accessed", c.get("year", "")))
        url, is_valid = validate_citation_url(c.get("url", c.get("source_url", "")))
        # F-04: URL displayed only in this section, with CSS word-break
        url_html = f'<span class="citation-url">{_e(url)}</span>' if is_valid else f'<span class="citation-url no-url">{_e(url)}</span>'
        rows += f"""<tr>
          <td class="cit-num">[{num}]</td>
          <td><strong>{name}</strong>{f" · {publisher}" if publisher else ""}</td>
          <td>{accessed}</td>
          <td>{url_html}</td>
        </tr>"""
    return f"""
<div class="section citations-section" id="s-citations">
  <h2><span class="sec-sym">§</span> Citations</h2>
  <table class="data-table citations-table">
    <thead><tr><th>#</th><th>Source</th><th>Date</th><th>URL</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</div>"""


def _render_recommended_steps(steps: list) -> str:
    if not steps:
        return ""
    items = "".join(f"<li>{_e(clean_list_item(s))}</li>" for s in steps if s and s.strip())
    return f"""
<div class="section" id="s-next-steps">
  <h2><span class="sec-num"></span> Recommended Next Steps</h2>
  <ol class="next-steps">{items}</ol>
</div>"""


# ── CSS ───────────────────────────────────────────────────────────────────────

def _sanitize_for_css(text: str) -> str:
    """Strip HTML tags and escape for safe embedding in a CSS string literal."""
    clean = re.sub(r'<[^>]+>', '', text)           # remove any HTML tags
    clean = clean.replace("\\", "\\\\")            # escape backslashes first
    clean = clean.replace("'", "\\'").replace('"', '\\"')   # escape quotes
    return clean


def _build_css(product_name: str) -> str:
    # F-09 type scale, F-07 @page running heads
    # Design: deep indigo accent, Charter/Georgia body serif, system-ui for labels
    # The running head text is set at render time via CSS custom property
    escaped_name = _sanitize_for_css(product_name)
    return f"""
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

    /* ── Tokens ── */
    :root {{
      --paper:        #FAFAF9;
      --ink:          #1E1E1E;
      --body:         #2D2D2D;
      --muted:        #6B7280;
      --accent:       #1B2550;
      --accent-surf:  #EDF0F7;
      --rule:         #D4D8E2;
      --link:         #1B4FD8;
      --exclude-bg:   #FEF2F2;
      --rec-bg:       #F0FDF4;
      --nontarget-bg: #FFF7ED;

      /* F-09 type scale */
      --t-xl:   22pt;
      --t-lg:   14pt;
      --t-md:   11pt;
      --t-sm:   9.5pt;
      --t-xs:   8pt;
    }}

    /* ── Base ── */
    html, body {{
      background: var(--paper);
      color: var(--body);
      font-family: 'Charter', 'Bitstream Charter', Georgia, 'Times New Roman', serif;
      font-size: var(--t-md);
      line-height: 1.52;
      -webkit-print-color-adjust: exact;
      print-color-adjust: exact;
    }}

    /* F-09: 70ch measure, centered */
    .page-content {{
      max-width: 70ch;
      margin: 0 auto;
      padding: 0 1rem;
    }}

    /* ── F-07 @page running heads ── */
    @page {{
      size: letter;
      margin: 1.25in 1in 1in 1in;
      @top-left   {{ content: "{escaped_name} · Commercial Intelligence Report";
                    font-family: system-ui, -apple-system, sans-serif;
                    font-size: 7.5pt; color: #6B7280; }}
      @top-right  {{ content: counter(page) " of " counter(pages);
                    font-family: system-ui, -apple-system, sans-serif;
                    font-size: 7.5pt; color: #6B7280; }}
      @bottom-right {{ content: "Not investment advice.";
                       font-family: system-ui, -apple-system, sans-serif;
                       font-size: 7pt; color: #9CA3AF; }}
    }}
    /* F-07: No running head on page 1 (title page) */
    @page :first {{
      @top-left   {{ content: ""; }}
      @top-right  {{ content: ""; }}
      @bottom-right {{ content: ""; }}
    }}

    /* ── Cover / page 1 masthead ── */
    .cover {{
      padding: 3rem 0 2.5rem;
      border-bottom: 2.5pt solid var(--accent);
      margin-bottom: 2.5rem;
    }}
    .cover .eyebrow {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: var(--t-sm);
      font-weight: 500;
      letter-spacing: .08em;
      text-transform: uppercase;
      color: var(--accent);
      margin-bottom: .5rem;
    }}
    .cover h1 {{
      font-size: var(--t-xl);
      font-weight: 700;
      color: var(--ink);
      line-height: 1.2;
      margin-bottom: .6rem;
      text-wrap: balance;
    }}
    .cover .meta {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: var(--t-sm);
      color: var(--muted);
    }}
    /* F-02: medlevate attribution only — routing/panel labels hidden from user */
    .cover .generated-by {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: var(--t-xs);
      color: var(--muted);
      margin-top: .4rem;
    }}

    /* ── Sections — G.11: auto-numbering via CSS counter ── */
    .page-content {{
      counter-reset: section;
    }}
    .section {{
      margin-bottom: 2.4rem;
      page-break-inside: avoid;
      counter-increment: section;
    }}
    h2 {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: var(--t-md);
      font-weight: 600;
      color: var(--ink);
      letter-spacing: .01em;
      margin-bottom: .75rem;
      padding-bottom: .3rem;
      border-bottom: .75pt solid var(--rule);
      display: flex;
      align-items: baseline;
      gap: .5rem;
      break-after: avoid;
    }}
    h3 {{
      font-family: system-ui, -apple-system, sans-serif;
      font-size: var(--t-sm);
      font-weight: 600;
      color: var(--ink);
      margin: 1rem 0 .4rem;
      break-after: avoid;
    }}
    .sec-num {{
      color: var(--accent);
      font-variant-numeric: tabular-nums;
      min-width: 1.6rem;
      display: inline-block;
    }}
    .sec-num::before {{
      content: counter(section);
    }}
    .sec-sym {{
      color: var(--accent);
      display: inline-block;
    }}
    p {{ margin-bottom: .65rem; }}
    ul, ol {{ padding-left: 1.4rem; margin-bottom: .65rem; }}
    li {{ margin-bottom: .25rem; line-height: 1.45; }}

    /* ── F-08 Tables ── */
    .data-table {{
      width: 100%;
      border-collapse: collapse;
      font-family: system-ui, -apple-system, sans-serif;
      font-size: var(--t-sm);
      margin-bottom: 1rem;
      break-inside: avoid;
    }}
    .data-table thead th {{
      background: var(--accent-surf);
      color: var(--accent);
      font-weight: 600;
      font-size: var(--t-xs);
      letter-spacing: .05em;
      text-transform: uppercase;
      padding: .35rem .55rem;
      text-align: left;
      border-bottom: 1.5pt solid var(--accent);
    }}
    .data-table tbody td {{
      padding: .3rem .55rem;
      vertical-align: top;
      border-bottom: .5pt solid var(--rule);
      /* F-03: no character cap; F-04: no injected whitespace */
      overflow-wrap: break-word;
      word-break: break-word;
    }}
    .data-table tbody tr:last-child td {{ border-bottom: none; }}
    .data-table tbody tr:nth-child(even) td {{ background: rgba(0,0,0,.02); }}

    /* F-09: tabular figures in numeric columns */
    .num {{ font-variant-numeric: tabular-nums; text-align: right; white-space: nowrap; }}
    .col-label {{ white-space: nowrap; font-weight: 500; }}
    .note {{ color: var(--muted); font-size: var(--t-xs); }}

    /* Row state colors (F-08) */
    tr.exclude td {{ background: var(--exclude-bg) !important; }}
    tr.recommended td {{ background: var(--rec-bg) !important; }}
    tr.nontarget td {{ background: var(--nontarget-bg) !important; }}
    .risk-cell {{ color: #B91C1C; }}

    /* ── F-04: URLs only in citations section, with safe CSS word-break ── */
    .citations-section .citation-url {{
      font-family: 'Courier New', Courier, monospace;
      font-size: var(--t-xs);
      color: var(--link);
      word-break: break-all;  /* F-04: line breaks at any char, never inserts spaces */
      hyphens: none;          /* F-04: no hyphenation inside URLs */
      display: block;
    }}
    .citation-url.no-url {{ color: var(--muted); font-style: italic; }}
    .cit-num {{ white-space: nowrap; color: var(--muted); font-variant-numeric: tabular-nums; }}

    /* ── F-05: citations without URLs styled distinctly ── */
    a {{ color: var(--link); text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}

    /* ── Supporting elements ── */
    .formula {{ font-family: 'Courier New', Courier, monospace; font-size: var(--t-sm);
                background: var(--accent-surf); padding: .4rem .6rem; border-radius: 2pt;
                margin-bottom: .65rem; }}
    .summary-row {{ display: flex; gap: 2rem; margin: .8rem 0 .65rem; flex-wrap: wrap; }}
    .summary-row > div {{ display: flex; flex-direction: column; }}
    .summary-row dt {{ font-family: system-ui, sans-serif; font-size: var(--t-xs);
                       text-transform: uppercase; letter-spacing: .06em; color: var(--muted); }}
    .summary-row dd {{ font-size: var(--t-md); font-weight: 600; color: var(--ink);
                       font-variant-numeric: tabular-nums; }}
    .summary-row dd.big {{ font-size: var(--t-lg); color: var(--accent); }}

    .methodology {{ font-size: var(--t-xs); color: var(--muted); font-style: italic;
                    border-left: 2pt solid var(--rule); padding-left: .6rem; }}
    .honest-empty {{ font-style: italic; color: var(--muted); padding: .5rem .6rem;
                     border-left: 2pt solid var(--rule); font-size: var(--t-sm); }}
    .positioning {{ border-left: 3pt solid var(--accent); padding: .6rem .8rem;
                    color: var(--ink); font-size: var(--t-md); font-style: italic; }}
    .guiding-question {{ font-size: var(--t-md); font-weight: 600; color: var(--accent);
                         border: 1pt solid var(--rule); padding: .6rem .8rem;
                         background: var(--accent-surf); }}
    .risk-list li {{ margin-bottom: .4rem; }}
    .kol-list li {{ font-size: var(--t-sm); margin-bottom: .2rem; }}
    .section-note {{ font-size: var(--t-xs); color: var(--muted); margin-bottom: .6rem; }}
    .table-note {{ font-size: var(--t-xs); color: var(--muted); font-style: italic; margin-top: -.4rem; }}
    .adversarial-table th, .adversarial-table td {{ font-size: var(--t-xs); }}
    .next-steps li {{ margin-bottom: .35rem; }}

    /* ── F-07: Footer disclaimer on final page ── */
    .footer-disclaimer {{
      margin-top: 2rem;
      padding-top: .8rem;
      border-top: .75pt solid var(--rule);
      font-family: system-ui, -apple-system, sans-serif;
      font-size: var(--t-xs);
      color: var(--muted);
      line-height: 1.4;
    }}

    /* ── F-07: Table of Contents ── */
    .toc {{
      page-break-before: always;
      page-break-after: always;
      padding: 2rem 0;
    }}
    .toc h2 {{
      font-size: var(--t-lg);
      color: var(--accent);
      margin-bottom: 1.5rem;
      border-bottom: 1.5pt solid var(--accent);
      padding-bottom: .4rem;
    }}
    .toc ol {{
      list-style: none;
      margin: 0;
      padding: 0;
    }}
    .toc ol li {{
      display: flex;
      align-items: baseline;
      gap: .5rem;
      padding: .35rem 0;
      border-bottom: .5pt dotted var(--rule);
      font-size: var(--t-sm);
    }}
    .toc ol li .toc-num {{
      font-family: system-ui, -apple-system, sans-serif;
      color: var(--muted);
      font-variant-numeric: tabular-nums;
      min-width: 2.4rem;
    }}
    .toc ol li a {{
      color: var(--body);
      text-decoration: none;
      flex: 1;
    }}

    /* ── A-02: Mock / demo watermark ── */
    .mock-banner {{
      background: #FEF3C7;
      color: #78350F;
      border: 1.5pt solid #D97706;
      padding: .45rem .75rem;
      margin-bottom: 1.5rem;
      font-family: system-ui, -apple-system, sans-serif;
      font-size: var(--t-sm);
      font-weight: 600;
      text-align: center;
      border-radius: 3pt;
    }}

    /* ── @media print overrides ── */
    @media print {{
      body {{ background: white; }}
      .section {{ page-break-inside: avoid; }}
      .toc {{ page-break-after: always; }}
      h2 {{ break-after: avoid; }}
      h3 {{ break-after: avoid; }}
      .data-table {{ break-inside: avoid; }}
      blockquote {{ break-inside: avoid; }}
      orphans: 3;
      widows: 3;
    }}
"""


# ── Main renderer ─────────────────────────────────────────────────────────────

def render_report_html(
    report: dict,
    product_name: str = "",
    institution: str = "",
    report_date: str = "",
    mock_mode: bool = False,
) -> str:
    """
    Converts a PIReport dict to a self-contained, print-ready HTML document.
    Addresses F-01 through F-09.

    Args:
        report:       PIReport serialized as dict (model.model_dump(mode="json"))
        product_name: F-01 intake field. If empty, derived from idea_submitted.
        institution:  F-01 meta line (e.g. "Washington University Neurotech Hub")
        report_date:  ISO date string. If empty, uses report.generated_at.
        mock_mode:    When True (or when report.model_version starts with "mock"),
                      injects a DEMO watermark banner so sample reports are never
                      mistaken for real outputs.
    """
    pname = product_name or derive_product_name(report)
    is_mock = mock_mode or (report.get("model_version") or "").lower().startswith("mock")
    domain_label = derive_domain_label(report)
    date_str = derive_report_date(report, report_date)
    institution = institution or (report.get("institution") or "")

    meta_parts = [p for p in [domain_label, institution, date_str] if p]
    meta_line = " · ".join(meta_parts)

    # F-02: expert_name hidden in HTML comment, not rendered
    expert_name = report.get("expert_name", "")
    expert_comment = f"<!-- generated by: {html.escape(expert_name)} -->" if expert_name else ""

    css = _build_css(pname)

    # Executive summary — C.3: strip any leading negation phrase
    exec_summary = _e(strip_negation(report.get("executive_summary", "") or ""))
    exec_html = f"""
<div class="section" id="s-executive">
  <h2><span class="sec-num"></span> The Opportunity</h2>
  <p>{exec_summary}</p>
</div>""" if exec_summary else ""

    # Limitations / evidence base (S-01)
    lim = report.get("limitations") or ""
    eb = report.get("evidence_base") or {}
    evid_html = ""
    if eb or lim:
        ev_quality = _e(eb.get("quality_summary", eb.get("summary", lim)))
        ev_gaps = _e(eb.get("key_gaps", ""))
        ev_method = _e(eb.get("methodology", ""))
        evid_html = f"""
<div class="section" id="s-evidence">
  <h2><span class="sec-num"></span> Evidence Base &amp; Limitations</h2>
  {f'<p>{ev_quality}</p>' if ev_quality else ""}
  {f'<p><strong>Key gaps:</strong> {ev_gaps}</p>' if ev_gaps else ""}
  {f'<p><strong>Methodology:</strong> {ev_method}</p>' if ev_method else ""}
</div>"""

    # Market sizing (F-08 tables)
    ms_html = _render_market_sizing(report.get("market_sizing") or {})

    # C.1/C.2: axis selection/rejection table
    axis_html = _render_axis_decisions(report.get("axis_decisions") or {})

    # Regulatory pathway — suppress for LIFE_SCIENCES_RESEARCH domain (Part C)
    _domain = (report.get("domain") or "").upper()
    _is_research_domain = _domain == "LIFE_SCIENCES_RESEARCH"
    if _is_research_domain and report.get("regulatory_pathway") is None:
        rp_html = f"""
<div class="section" id="s-regulatory">
  <h2><span class="sec-num"></span> Regulatory &amp; Compliance Overview</h2>
  <p><strong>FDA jurisdiction: not required.</strong> This product is a non-clinical research
  tool sold exclusively to academic investigators. It falls outside 21 U.S.C. § 321(h) — its
  intended use is data capture and analysis for research purposes, not to diagnose, treat,
  cure, or prevent disease in any patient. No 510(k), De Novo, PMA, NDA, or BLA is required.</p>

  <h3>What does apply</h3>
  <table class="data-table">
    <thead><tr><th>Requirement</th><th>Trigger</th><th>Action</th><th>Est. Cost / Timeline</th></tr></thead>
    <tbody>
      <tr>
        <td>IRB / IACUC review</td>
        <td>Device worn by or implanted near human or animal research subjects</td>
        <td>File protocol with institutional review board before any human-subjects pilot</td>
        <td>$0–$5k; 4–12 weeks</td>
      </tr>
      <tr>
        <td>Intended-use legal opinion</td>
        <td>Required before commercial launch to confirm non-device status</td>
        <td>Engage regulatory counsel to document intended-use exclusion in writing</td>
        <td>$15k–$40k; 1–2 months</td>
      </tr>
      <tr>
        <td>Export controls (EAR / ITAR)</td>
        <td>Bluetooth or RF hardware shipped internationally; data encrypted at rest</td>
        <td>Classify hardware under Commerce Control List (CCL); file EAR self-classification if needed</td>
        <td>$5k–$15k; 4–8 weeks</td>
      </tr>
      <tr>
        <td>Bayh-Dole / IP obligations</td>
        <td>Development funded by NIH, NSF, or other federal grants</td>
        <td>Notify TTO of invention; license back rights if required by grant terms</td>
        <td>Internal; immediate</td>
      </tr>
      <tr>
        <td>FCC Part 15 / Bluetooth certification</td>
        <td>Any radio-frequency device sold in the US</td>
        <td>Use pre-certified Bluetooth module or obtain Part 15 authorization for custom hardware</td>
        <td>$5k–$25k; 2–4 months</td>
      </tr>
      <tr>
        <td>State lab safety / OSHA</td>
        <td>Device operates in university lab environment</td>
        <td>Confirm electrical safety (UL listing or equivalent) and EMI compliance</td>
        <td>Typically covered by FCC cert above</td>
      </tr>
    </tbody>
  </table>

  <h3>Pathway to regulated status (watch-outs)</h3>
  <p>FDA jurisdiction would attach if the product were ever marketed with a diagnostic or
  therapeutic claim, used to influence a clinical decision, or sold to hospitals for patient
  monitoring. Maintain strict intended-use language in all marketing materials, contracts, and
  product labeling. Any rebranding toward clinical use triggers a fresh regulatory assessment.</p>
</div>"""
    else:
        rp_html = _render_regulatory_pathway(report.get("regulatory_pathway") or {})

    # Market access — suppress for LIFE_SCIENCES_RESEARCH domain (Part C)
    if _is_research_domain and report.get("market_access") is None:
        ma_html = """
<div class="section" id="s-access">
  <h2><span class="sec-num"></span> Market Access</h2>
  <p class="honest-empty">Traditional payer/reimbursement analysis is not applicable
  for non-clinical research tools. Access is through direct institutional sales,
  NIH/NSF equipment grants, lab CAPEX budgets, and indirect cost recovery.
  See the Market Sizing section for buyer segment and revenue model details.</p>
</div>"""
    else:
        ma_html = _render_market_access(report.get("market_access") or {})

    # Competitive landscape
    ci_html = _render_competitive_landscape(report.get("competitive_landscape") or {})

    # P1 strategic sections (S-02 through S-09)
    p1_html = _render_p1_sections(report)

    # Recommended next steps
    steps_html = _render_recommended_steps(report.get("recommended_next_steps", []))

    # Citations (F-04, F-05) — aggregate same sources as web renderer (G-01 parity)
    _all_cits: list = list(report.get("sources") or [])
    _seen_cit_urls: set = {c.get("url") for c in _all_cits if c.get("url")}

    def _add_cit_by_url(name: str, url: str) -> None:
        """Add a citation discovered by URL only (strategies, segments). Skips if no URL."""
        if not url or url in _seen_cit_urls:
            return
        _seen_cit_urls.add(url)
        _all_cits.append({"name": name, "url": url})

    # Literature citations always appear even when they lack a URL (F-05 no-URL marker).
    # Deduplicate by URL only when a URL is actually present.
    for _p in report.get("literature_citations") or []:
        _purl = (
            _p.get("url")
            or _p.get("source_url")
            or (f"https://pubmed.ncbi.nlm.nih.gov/{_p['pmid']}/" if _p.get("pmid") else "")
        )
        if _purl and _purl in _seen_cit_urls:
            continue
        if _purl:
            _seen_cit_urls.add(_purl)
        # Preserve the original dict (keeps name, number, year etc.); patch url if needed
        _entry = dict(_p)
        if _purl and not _entry.get("url"):
            _entry["url"] = _purl
        elif not _entry.get("name"):
            _entry["name"] = (
                f"{_p.get('authors', '')} ({_p.get('year', '')}). {_p.get('title', '')}.".strip()
            )
        _all_cits.append(_entry)

    for _s in report.get("strategic_playbook") or []:
        _add_cit_by_url(
            f"{_s.get('example', '')} — {_s.get('strategy', '')}",
            _s.get("source_url", ""),
        )

    for _b in (report.get("market_access") or {}).get("buyer_segments") or []:
        _add_cit_by_url(
            f"{_b.get('source', '')} — {_b.get('segment_name', _b.get('segment', ''))}",
            _b.get("source_url", ""),
        )

    _reimb_url = (report.get("market_access") or {}).get("reimbursement_source_url")
    if _reimb_url:
        _add_cit_by_url("Reimbursement pathway source", _reimb_url)

    for _ci, _cc in enumerate(_all_cits):
        _cc["number"] = _ci + 1

    cit_html = _render_citations(_all_cits)

    # Footer disclaimer (F-07: once, at bottom)
    disclaimer = (
        "This report was generated by Medlevate using publicly available data sources. "
        "It does not constitute legal, regulatory, or investment advice. "
        "All market estimates carry inherent uncertainty. "
        "Consult domain specialists before making material business decisions."
    )

    # G.11: dynamic TOC with sequential numbers — only present sections get numbers.
    # Suppressed sections (e.g. adversarial review when empty) don't create gaps.
    _toc_rows = _build_toc([
        (bool(exec_html),                    "s-executive",    "The Opportunity"),
        (bool(evid_html),                    "s-evidence",     "Evidence Base &amp; Limitations"),
        (bool(ms_html),                      "s-market",       "Market Sizing"),
        (bool(rp_html),                      "s-regulatory",   "Regulatory &amp; Compliance Overview"),
        (bool(ma_html),                      "s-access",       "Market Access &amp; Commercial Strategy"),
        (bool(ci_html),                      "s-competitive",  "Competitive Landscape"),
        ("s-value-drivers" in p1_html,       "s-value-drivers","Value Driver Ranking"),
        ("s-segments"      in p1_html,       "s-segments",     "Segment Fit"),
        ("s-features"      in p1_html,       "s-features",     "Feature Investment Posture"),
        ("s-pricing"       in p1_html,       "s-pricing",      "Pricing Model Analysis"),
        ("s-positioning"   in p1_html,       "s-positioning",  "Positioning Statement"),
        ("s-risks"         in p1_html,       "s-risks",        "Strategic Risks"),
        ("s-guiding"       in p1_html,       "s-guiding",      "Guiding Question"),
        ("s-adversarial"   in p1_html,       "s-adversarial",  "Adversarial Review"),
        (bool(steps_html),                   "s-next-steps",   "Recommended Next Steps"),
        (bool(cit_html),                     "s-citations",    "Citations"),
    ])
    toc_html = f"""
  <!-- F-07: Table of Contents (dynamic — empty sections omitted) -->
  <nav class="toc" aria-label="Table of contents">
    <h2>Contents</h2>
    <ol>
{_toc_rows}
    </ol>
  </nav>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{_e(pname)} — Commercial Intelligence Report</title>
  <meta name="author" content="Medlevate{(' — ' + _e(institution)) if institution else ''}">
  <meta name="subject" content="{_e(domain_label)} · Commercial Intelligence Report">
  <meta name="description" content="Commercial intelligence report for {_e(pname)}">
  {expert_comment}
  <style>{css}</style>
</head>
<body>
<div class="page-content">

  <!-- F-01: product name as title; F-02: no expert_name in user-visible content -->
  <header class="cover">
    <p class="eyebrow">Commercialization Intelligence Report</p>
    <h1>{_e(pname)}</h1>
    <p class="meta">{_e(meta_line)}</p>
    <p class="generated-by">Prepared by Medlevate</p>
  </header>
  {"<div class='mock-banner' role='alert'>DEMO REPORT — Generated with sample data. Not for investment decisions or distribution.</div>" if is_mock else ""}
  {toc_html}

  {exec_html}
  {evid_html}
  {ms_html}
  {axis_html}
  {rp_html}
  {ma_html}
  {ci_html}
  {p1_html}
  {steps_html}
  {cit_html}

  <!-- F-07: disclaimer once, at bottom -->
  <footer class="footer-disclaimer">
    <p>{_e(disclaimer)}</p>
  </footer>

</div>
</body>
</html>"""


# ── PDF bytes via playwright (optional; graceful fallback) ────────────────────

async def generate_pdf(
    report: dict,
    product_name: str = "",
    institution: str = "",
    report_date: str = "",
) -> bytes:
    """
    Render HTML to PDF bytes via headless Chromium (playwright).
    Falls back to HTML bytes (UTF-8) when playwright is not installed.
    """
    html_str = render_report_html(report, product_name, institution, report_date)
    pname = product_name or derive_product_name(report)

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.warning(
            "pdf_renderer: playwright not installed — returning HTML. "
            "Install with: pip install playwright && playwright install chromium"
        )
        return html_str.encode("utf-8")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html_str, wait_until="networkidle")
            pdf_bytes = await page.pdf(
                format="Letter",
                margin={"top": "1.25in", "bottom": "1in",
                        "left": "1in",   "right": "1in"},
                display_header_footer=False,  # F-07: we use @page CSS instead
                print_background=True,
            )
            await browser.close()
            logger.info("pdf_renderer: generated %d bytes for '%s'", len(pdf_bytes), pname)
            return pdf_bytes
    except Exception as exc:
        logger.error("pdf_renderer: playwright error — returning HTML: %s", exc)
        return html_str.encode("utf-8")
