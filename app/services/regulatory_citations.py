"""
Regulatory Citation Lookup Table  (B-06)
=========================================
Curated, verified mapping of regulatory citations used in Medlevate reports.

Design:
  Generators reference table KEYS, not free-text CFR/statute cites.
  Anything not in this table cannot be cited. This prevents:
    - Wrong CFR section for CDS exclusion (21 CFR 807.3(b) vs FD&C 520(o)(1)(E))
    - Wrong year on guidance documents (CDS 2019 vs 2022)
    - Fabricated predicate K-numbers

Usage:
  from app.services.regulatory_citations import get_citation, validate_cfr_cite

  cite = get_citation("cures_cds_exclusion")
  # → {"title": "...", "url": "...", "year": 2022, ...}

  is_valid, corrected = validate_cfr_cite("21 CFR 807.3(b)")
  # → (False, "This section defines 'device' within establishment registration — not an exclusion mechanism. Use FD&C Act section 520(o)(1)(E) for the CDS carve-out.")
"""

from __future__ import annotations
from typing import Optional

# ── Citation registry ─────────────────────────────────────────────────────────

REGULATORY_CITATIONS: dict[str, dict] = {

    # ── CDS / Software ────────────────────────────────────────────────────────
    "cures_cds_exclusion": {
        "key":     "cures_cds_exclusion",
        "title":   "21st Century Cures Act — Section 3060, FD&C Act § 520(o)(1)(E): CDS software exclusion from device definition",
        "year":    2016,
        "url":     "https://www.congress.gov/114/plaws/publ255/PLAW-114publ255.pdf",
        "note":    "The CDS carve-out lives in FD&C Act § 520(o)(1)(E), added by the 21st Century Cures Act (2016). NOT in 21 CFR 807.3(b), which is only a definitions section for establishment registration.",
        "type":    "statute",
    },
    "fda_cds_guidance_2022": {
        "key":     "fda_cds_guidance_2022",
        "title":   "FDA Final Guidance: Clinical Decision Support Software (September 2022)",
        "year":    2022,
        "url":     "https://www.fda.gov/media/153896/download",
        "note":    "Final guidance issued September 2022. A draft was issued in 2019, but the FINAL guidance is 2022. Cite as '2022 CDS guidance', not '2019'.",
        "type":    "fda_guidance",
    },
    "21cfr_807_3b": {
        "key":     "21cfr_807_3b",
        "title":   "21 CFR 807.3(b) — Definition of 'device' within establishment registration and device listing",
        "year":    None,
        "url":     "https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-807/subpart-A/section-807.3",
        "note":    "IMPORTANT: This section defines 'device' for purposes of 21 CFR Part 807 (establishment registration) ONLY. It is NOT an exclusion mechanism. Do not cite it as the basis for excluding a product from device jurisdiction. Use FD&C Act § 520(o) for exclusions.",
        "type":    "cfr",
        "common_error": "Cited as a device exclusion mechanism. This is wrong — it is only a definitions provision.",
    },
    "fda_predetermined_change_control": {
        "key":     "fda_predetermined_change_control",
        "title":   "FDA Guidance: Predetermined Change Control Plans for Machine Learning-Enabled Medical Devices (December 2024)",
        "year":    2024,
        "url":     "https://www.fda.gov/regulatory-information/search-fda-guidance-documents/predetermined-change-control-plans-machine-learning-enabled-medical-devices",
        "note":    "PCCP allows AI/ML device makers to describe planned modifications in an approved plan, reducing the need for new submissions for each software update.",
        "type":    "fda_guidance",
    },

    # ── Drug regulatory ───────────────────────────────────────────────────────
    "fdca_505b2": {
        "key":     "fdca_505b2",
        "title":   "FD&C Act § 505(b)(2) — New Drug Application relying on published literature or FDA findings",
        "year":    None,
        "url":     "https://www.fda.gov/drugs/types-applications/505b2-applications",
        "note":    "Allows NDA applicants to rely on existing data not developed by the applicant. Applicable to new formulations, new routes, new indications of approved drugs.",
        "type":    "statute",
    },
    "qidp_lpad": {
        "key":     "qidp_lpad",
        "title":   "Generating Antibiotic Incentives Now (GAIN) Act — QIDP and Limited Population Pathway (LPAD)",
        "year":    2012,
        "url":     "https://www.fda.gov/patients/fast-track-breakthrough-therapy-accelerated-approval-priority-review/qualified-infectious-disease-product-designation",
        "note":    "QIDP designation adds 5 years to exclusivity and grants Fast Track + Priority Review. LPAD (21st Century Cures Act, 2016) is a separate approval pathway for unmet need in a limited population.",
        "type":    "statute",
    },
    "pasteur_act": {
        "key":     "pasteur_act",
        "title":   "PASTEUR Act (Pioneering Antimicrobial Subscriptions To End Upsurging Resistance) — proposed subscription payment model for novel antibiotics",
        "year":    2023,
        "url":     "https://www.congress.gov/bill/118th-congress/senate-bill/2041",
        "note":    "As of 2025, not yet enacted. Passed Senate Judiciary in 2023. Do NOT describe as law — describe as pending legislation.",
        "type":    "proposed_legislation",
        "status":  "pending",
    },

    # ── Device regulatory ─────────────────────────────────────────────────────
    "510k_pathway": {
        "key":     "510k_pathway",
        "title":   "21 CFR Part 807 Subpart E — Premarket Notification (510(k))",
        "year":    None,
        "url":     "https://www.fda.gov/medical-devices/premarket-submissions-selecting-and-preparing-correct-submission/premarket-notification-510k",
        "note":    "Device clearance pathway for Class II devices demonstrating substantial equivalence to a legally marketed predicate. Applicant name and device name must be retrieved from openFDA, not generated.",
        "type":    "cfr",
    },
    "de_novo_pathway": {
        "key":     "de_novo_pathway",
        "title":   "21 CFR Part 860 Subpart D — De Novo Classification Request",
        "year":    None,
        "url":     "https://www.fda.gov/medical-devices/premarket-submissions-selecting-and-preparing-correct-submission/de-novo-classification-request",
        "note":    "For novel low-to-moderate-risk devices with no valid predicate. Creates a new Class II classification and a de novo order that can serve as a predicate for future 510(k)s.",
        "type":    "cfr",
    },
    "pma_pathway": {
        "key":     "pma_pathway",
        "title":   "21 CFR Part 814 — Premarket Approval Application (PMA)",
        "year":    None,
        "url":     "https://www.fda.gov/medical-devices/premarket-submissions-selecting-and-preparing-correct-submission/premarket-approval-pma",
        "note":    "Required for Class III (high-risk) devices. Requires valid scientific evidence demonstrating safety and effectiveness.",
        "type":    "cfr",
    },
    "breakthrough_device": {
        "key":     "breakthrough_device",
        "title":   "21st Century Cures Act § 3051 — Breakthrough Device Designation",
        "year":    2016,
        "url":     "https://www.fda.gov/patients/fast-track-breakthrough-therapy-accelerated-approval-priority-review/breakthrough-devices-program",
        "note":    "Provides for more interactive and timely communication with FDA during development; does NOT guarantee approval or accelerated decision timeline.",
        "type":    "statute",
    },

    # ── Reimbursement ─────────────────────────────────────────────────────────
    "ntap": {
        "key":     "ntap",
        "title":   "CMS New Technology Add-on Payment (NTAP) — 42 CFR § 412.87",
        "year":    None,
        "url":     "https://www.cms.gov/medicare/payment/prospective-payment-systems/acute-inpatient-pps/new-medical-services-and-new-technologies/add-on-payments",
        "note":    "Inpatient hospital supplemental payment for technologies meeting newness, substantial clinical improvement, and cost criteria. NOT applicable to outpatient, physician office, or research-use products.",
        "type":    "cfr",
    },
    "cpt_rpm": {
        "key":     "cpt_rpm",
        "title":   "CMS Remote Patient Monitoring CPT Codes (99453, 99454, 99457, 99458)",
        "year":    2019,
        "url":     "https://www.cms.gov/Medicare/Coverage/center-for-connected-care-and-telehealth/rpm",
        "note":    "Reimbursement codes for remote physiologic monitoring services. Requires FDA-cleared device, clinical supervision, and care plan documentation. NOT applicable to research-use products.",
        "type":    "cms_code",
    },

    # ── Research / non-clinical ───────────────────────────────────────────────
    "research_tool_not_regulated": {
        "key":     "research_tool_not_regulated",
        "title":   "FD&C Act § 201(h) — Definition of 'device' (intended use determines jurisdiction)",
        "year":    None,
        "url":     "https://www.fda.gov/medical-devices/overview-device-regulation/classify-your-medical-device",
        "note":    "A product sold exclusively for research use with no clinical claim is not a device under FD&C § 201(h) because its intended use is not to diagnose, cure, treat, prevent, or mitigate disease. A legal opinion ($15k–$40k, 1–2 months) confirms this; a 510(k) is not needed and should not be recommended.",
        "type":    "statute",
    },
    "sbir_eligibility": {
        "key":     "sbir_eligibility",
        "title":   "Small Business Innovation Research (SBIR) Program — SBA SBIR/STTR Policy Directive",
        "year":    2019,
        "url":     "https://www.sbir.gov/sites/default/files/SBIR-STTR_Policy_Directive_2019.pdf",
        "note":    "Requires for-profit US small business with ≤500 employees; PI must be primarily employed by the company (≥51%) at time of award for SBIR Phase II.",
        "type":    "federal_program",
    },
}


# ── Known CFR/Statute errors ──────────────────────────────────────────────────

_KNOWN_ERRORS: dict[str, str] = {
    "21 cfr 807.3(b)": (
        "21 CFR 807.3(b) defines 'device' within the establishment registration regulations — "
        "it is NOT an exclusion mechanism. To cite the CDS software carve-out, use "
        "FD&C Act § 520(o)(1)(E), added by the 21st Century Cures Act (2016). "
        "See key: 'cures_cds_exclusion'."
    ),
    "21 cfr 807.3": (
        "21 CFR 807.3 is the definitions section of the establishment registration regulations, "
        "not an exclusion provision. For CDS exclusion, use FD&C Act § 520(o)(1)(E)."
    ),
    "cds guidance 2019": (
        "The FDA CDS Final Guidance was issued in September 2022, not 2019. "
        "A draft guidance was issued in 2019, but the final guidance effective date is 2022. "
        "Cite as '2022 CDS guidance'. See key: 'fda_cds_guidance_2022'."
    ),
    "pasteur act": (
        "As of 2025, the PASTEUR Act has NOT been enacted into law. "
        "It passed the Senate Judiciary Committee in 2023 but has not been signed. "
        "Describe as 'pending legislation', not as existing law."
    ),
}


# ── Public API ─────────────────────────────────────────────────────────────────

def get_citation(key: str) -> Optional[dict]:
    """Return the citation dict for a known key, or None."""
    return REGULATORY_CITATIONS.get(key)


def validate_cfr_cite(cite_text: str) -> tuple[bool, str]:
    """
    Check a free-text regulatory citation against known errors.
    Returns (is_correct, note_or_correction).

    is_correct=True  → no known error found; citation may still be wrong but
                        is not in our error table.
    is_correct=False → citation matches a known error; correction is provided.
    """
    lower = (cite_text or "").lower().strip()
    for pattern, correction in _KNOWN_ERRORS.items():
        if pattern in lower:
            return False, correction
    return True, ""


def all_keys() -> list[str]:
    """List all registered citation keys."""
    return list(REGULATORY_CITATIONS.keys())


def citations_for_type(cite_type: str) -> list[dict]:
    """Return all citations of a given type (e.g. 'cfr', 'statute', 'fda_guidance')."""
    return [c for c in REGULATORY_CITATIONS.values() if c.get("type") == cite_type]
