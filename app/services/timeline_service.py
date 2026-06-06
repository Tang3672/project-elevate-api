"""
Development Timeline Generator
================================
Converts a PIReport into a concrete, date-anchored development schedule
with Gantt phases, regulatory milestones, funding windows, and iCal export.

Structure:
  Phase 0  IND-enabling / preclinical
  Phase 1  First-in-human safety & PK
  Phase 2  Proof-of-concept efficacy
  Phase 3  Pivotal (registration)
  NDA/BLA  Submission package preparation
  FDA      Review period → Approval

Each phase carries:
  - start/end calendar dates
  - cost estimate
  - key activities
  - embedded regulatory and funding milestones

The timeline is product-type-aware: an antibiotic gets QIDP/LPAD windows
and CARB-X/BARDA funding calls; an oncology drug gets Breakthrough Therapy
and ODD applications; a device gets 510(k)/PMA milestones instead.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from typing import Optional


# ── Calendar helpers ──────────────────────────────────────────────────────────

def _add_months(d: date, months: int) -> date:
    return d + relativedelta(months=months)


def _quarter(d: date) -> str:
    q = (d.month - 1) // 3 + 1
    return f"{d.year} Q{q}"


def _fmt_date(d: date) -> str:
    return d.strftime("%B %Y")


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class TimelineMilestone:
    date:        str          # "June 2027"
    iso_date:    str          # "2027-06-01"
    event:       str
    type:        str          # "regulatory" | "funding" | "clinical" | "strategic"
    description: str = ""
    action_required: bool = True


@dataclass
class TimelinePhase:
    id:              str
    name:            str
    type:            str          # "preclinical" | "phase1" | "phase2" | "phase3" | "submission" | "review"
    start_date:      str
    end_date:        str
    start_iso:       str
    end_iso:         str
    duration_months: int
    cost_low_usd:    int
    cost_high_usd:   int
    cost_fmt:        str
    key_activities:  list[str]
    milestones:      list[dict]
    color:           str


@dataclass
class DevelopmentTimeline:
    product_type:              str
    disease:                   str
    idea_submitted:            str
    start_date:                str
    estimated_approval_date:   str
    estimated_approval_iso:    str
    total_duration_years:      float
    total_cost_low_usd:        int
    total_cost_high_usd:       int
    total_cost_fmt:            str
    phases:                    list[dict]
    regulatory_milestones:     list[dict]
    funding_windows:           list[dict]
    strategic_calendar:        list[dict]
    generated_at:              str
    probability_of_approval:   str
    key_risks:                 list[str]


# ── Phase colour palette ──────────────────────────────────────────────────────

_PHASE_COLORS = {
    "preclinical": "#6366f1",
    "phase1":      "#0891b2",
    "phase2":      "#059669",
    "phase3":      "#d97706",
    "submission":  "#dc2626",
    "review":      "#7c3aed",
}


# ── Product-type phase templates ──────────────────────────────────────────────
# (duration_months, cost_low_M, cost_high_M, activities)

_PRECLINICAL = {
    "drug_small_molecule": (14, 3,  8,  ["GLP toxicology (28/90-day)", "ADME/PK studies", "CMC scale-up", "Pre-IND meeting with FDA"]),
    "biologic":            (18, 5,  15, ["Cell-line development", "GLP tox + immunogenicity", "CMC process dev", "Pre-BLA meeting"]),
    "gene_cell_therapy":   (24, 10, 30, ["Vector manufacturing", "GLP biodistribution", "Genotoxicity studies", "GT product pre-IND meeting"]),
    "medical_device":      (12, 1,  5,  ["Bench testing", "Biocompatibility (ISO 10993)", "Pre-submission meeting (Q-sub)", "Design verification"]),
    "diagnostic":          (10, 1,  4,  ["Analytical validation", "Predicate device search", "510(k) pre-submission"]),
    "vaccine_immunotherapy":(18, 5, 15, ["Immunogenicity in animals", "Adjuvant selection", "CMC process", "Pre-IND meeting"]),
    "other":               (14, 3,  8,  ["GLP toxicology", "ADME studies", "CMC development", "Pre-IND meeting"]),
}

_PHASE1 = {
    "drug_small_molecule": (15, 8,  15, ["SAD/MAD dose escalation", "PK/PD characterisation", "Food effect", "DDI studies", "Safety monitoring board"]),
    "biologic":            (18, 12, 25, ["SAD/MAD in healthy volunteers + patients", "Immunogenicity", "PK/PD modelling", "First-patient-in"]),
    "gene_cell_therapy":   (24, 15, 40, ["Dose escalation in patients", "Long-term follow-up (15yr per FDA GT guidance)", "Biodistribution", "Safety run-in"]),
    "medical_device":      (6,  1,  4,  ["First-in-human feasibility", "Usability/human factors", "IDE (if needed)"]),
    "diagnostic":          (4,  1,  3,  ["Clinical validation study design", "IRB approval", "Site selection"]),
    "vaccine_immunotherapy":(18, 10, 20, ["Dose escalation", "Immunogenicity endpoints", "Reactogenicity", "DSMB oversight"]),
    "other":               (15, 8,  15, ["Safety escalation", "PK characterisation", "Biomarker development"]),
}

_PHASE2 = {
    "drug_small_molecule": (22, 20, 45, ["Proof-of-concept in target population", "Dose finding", "Biomarker validation", "Adaptive design consideration", "End-of-Phase 2 meeting with FDA"]),
    "biologic":            (24, 30, 60, ["Efficacy signal in patients", "PK/PD population model", "Immunogenicity assessment", "EoP2 meeting"]),
    "gene_cell_therapy":   (30, 40, 80, ["Single-arm efficacy", "Durability follow-up", "Patient registry setup", "EoP2 meeting"]),
    "medical_device":      (12, 3,  10, ["Pivotal study design and site selection", "IDE submission if Class III", "Protocol development"]),
    "diagnostic":          (8,  2,  6,  ["Sensitivity/specificity validation", "Multi-site clinical validation", "FDA pre-market notification prep"]),
    "vaccine_immunotherapy":(24, 25, 50, ["Immunogenicity + efficacy signals", "Correlates of protection", "EoP2 / type B meeting"]),
    "other":               (22, 20, 45, ["Efficacy signal", "Dose finding", "EoP2 meeting with FDA"]),
}

_PHASE3 = {
    "drug_small_molecule": (30, 80, 180, ["Pivotal registration trial(s)", "Pre-specified interim analysis", "Compassionate use / expanded access", "CMC tech transfer to commercial site", "Advisory committee preparation"]),
    "biologic":            (36, 100, 250, ["Pivotal BLA-enabling trial", "Comparator arm", "Long-term safety extension", "Commercial CMC validation", "AdCom preparation"]),
    "gene_cell_therapy":   (42, 120, 350, ["Pivotal trial with long-term follow-up", "Patient registry", "Risk mitigation strategy (REMS)", "Commercial vector manufacturing"]),
    "medical_device":      (18, 10, 40,  ["Pivotal IDE trial", "Statistical analysis plan", "510(k) or PMA compilation"]),
    "diagnostic":          (10, 3,  12,  ["Prospective multi-site validation", "CLIA/CAP lab validation", "Reimbursement coding (CPT)"]),
    "vaccine_immunotherapy":(36, 100, 300, ["Large-scale efficacy trial", "Safety surveillance", "Manufacturing scale-up", "ACIP recommendation preparation"]),
    "other":               (30, 80, 180, ["Pivotal trial", "Safety extension", "Commercial CMC"]),
}

_SUBMISSION = {
    "drug_small_molecule": (8, 5, 15, ["NDA assembly (CTD format)", "Integrated Summary of Safety", "Integrated Summary of Efficacy", "AdCom meeting", "REMS preparation if needed"]),
    "biologic":            (10, 8, 20, ["BLA assembly", "ISS/ISE", "Biosimilar strategy review", "AdCom meeting"]),
    "gene_cell_therapy":   (12, 10, 25, ["BLA assembly", "Long-term follow-up data integration", "REMS development", "Risk communication plan"]),
    "medical_device":      (6,  2, 8,  ["510(k) or PMA submission", "De novo if applicable", "Labelling finalisation"]),
    "diagnostic":          (4,  1, 4,  ["510(k) submission or PMA", "CLIA registration", "Coding and coverage dossier"]),
    "vaccine_immunotherapy":(10, 8, 20, ["BLA submission", "Manufacturing batch records", "ACIP package preparation"]),
    "other":               (8,  5, 15, ["NDA/BLA assembly", "Integrated summaries", "Labelling strategy"]),
}

_REVIEW = {
    "drug_small_molecule": (12, 2, 5, ["FDA review (PDUFA date)", "Response to FDA information requests", "Manufacturing pre-approval inspection (PAI)", "Launch preparation", "Commercial contracting and payor access"]),
    "biologic":            (12, 3, 6, ["FDA BLA review", "Facility inspection", "Biosimilar IP strategy", "Launch prep"]),
    "gene_cell_therapy":   (12, 3, 8, ["FDA BLA review", "REMS finalisation", "Specialty pharmacy network setup", "Patient support programme"]),
    "medical_device":      (6,  1, 3, ["510(k) review (90-day clock)", "PMA review (180-day clock)", "Post-market surveillance plan", "Commercial launch"]),
    "diagnostic":          (3,  0, 2, ["510(k) clearance", "Lab partnerships", "Coverage and coding"]),
    "vaccine_immunotherapy":(12, 3, 6, ["FDA review", "ACIP vote", "VFC contract negotiation", "Distribution network"]),
    "other":               (12, 2, 5, ["FDA review", "PAI", "Launch preparation"]),
}


# ── Regulatory milestones by product type ────────────────────────────────────

def _regulatory_milestones(product_type: str, start: date,
                             phase_ends: dict[str, date]) -> list[dict]:
    ms: list[dict] = []

    def _m(offset_from_start: int, event: str, desc: str, mtype: str = "regulatory") -> dict:
        d = _add_months(start, offset_from_start)
        return asdict(TimelineMilestone(
            date=_fmt_date(d), iso_date=d.isoformat(),
            event=event, type=mtype, description=desc,
        ))

    pre_ind_end   = phase_ends.get("preclinical", _add_months(start, 12))
    ph1_start     = pre_ind_end
    ph1_end       = phase_ends.get("phase1", _add_months(start, 27))
    ph2_end       = phase_ends.get("phase2", _add_months(start, 50))
    ph3_end       = phase_ends.get("phase3", _add_months(start, 82))

    # IND / equivalent
    ind_month = (pre_ind_end - start).days // 30
    ms.append(_m(max(ind_month - 2, 0),
                 "Pre-IND Meeting Request to FDA",
                 "Submit Type B meeting request 30 days before desired meeting date. "
                 "Use this meeting to align on IND package, nonclinical programme, and CMC strategy."))
    ms.append(_m(ind_month,
                 "IND Submission (or IDE for devices)",
                 "Submit Investigational New Drug Application. FDA has 30 days to place a clinical hold. "
                 "Notify IRB and initiate site activation in parallel."))

    ph1_end_month = (ph1_end - start).days // 30
    ms.append(_m(ph1_end_month,
                 "End-of-Phase 1 / Type B Meeting",
                 "Request Type B meeting to align on Phase 2 design, endpoints, biomarker strategy, "
                 "and any Special Protocol Assessment (SPA)."))

    ph2_end_month = (ph2_end - start).days // 30
    ms.append(_m(ph2_end_month - 2,
                 "End-of-Phase 2 Meeting Request",
                 "Submit meeting request 70 days before desired EoP2 meeting. "
                 "Critical gate: align on Phase 3 design, NDA/BLA data package, and statistical analysis plan."))
    ms.append(_m(ph2_end_month,
                 "End-of-Phase 2 / Type B Meeting with FDA",
                 "Discuss Phase 3 protocol, commercial CMC strategy, payor evidence requirements, "
                 "and eligibility for priority review or accelerated approval."))

    ph3_end_month = (ph3_end - start).days // 30
    ms.append(_m(ph3_end_month - 3,
                 "Pre-NDA/BLA Meeting",
                 "Discuss NDA/BLA format, labelling strategy, Risk Evaluation and Mitigation Strategy (REMS) "
                 "if needed, and advisory committee (AdCom) plan."))
    ms.append(_m(ph3_end_month,
                 "NDA/BLA Submission",
                 "Submit complete application package. FDA issues Filing Acceptance Letter within 60 days. "
                 "PDUFA date set (standard 12 months, priority 6 months from filing)."))

    # Product-specific designations
    if "antibiotic" in product_type or "amr" in product_type:
        ms.append(_m(max(ind_month - 6, 0),
                     "QIDP Designation Application (GAIN Act)",
                     "Submit QIDP request ≥90 days before NDA. Qualifies for +5yr exclusivity, Priority Review, "
                     "and automatic Fast Track. Must list the pathogen as a GAIN Act qualifying pathogen.",
                     "regulatory"))
        ms.append(_m(max(ind_month - 4, 0),
                     "Fast Track Designation Request",
                     "Automatic with QIDP; request independently in parallel. Allows rolling NDA submission "
                     "and monthly FDA interactions.",
                     "regulatory"))

    if product_type in ("gene_cell_therapy", "biologic"):
        ms.append(_m(max(ind_month - 3, 0),
                     "RMAT Designation Application",
                     "Regenerative Medicine Advanced Therapy designation for cell/gene therapies "
                     "treating serious conditions with unmet need. Provides intensive FDA guidance and "
                     "rolling review.",
                     "regulatory"))

    if product_type == "oncology":
        ms.append(_m(max(ind_month - 2, 0),
                     "Breakthrough Therapy Designation Application",
                     "Apply at or after IND; requires clinical evidence of substantial improvement over "
                     "available therapy on a clinically significant endpoint. Provides intensive FDA guidance.",
                     "regulatory"))

    ms.append(_m(max(ph1_end_month - 6, 0),
                 "Orphan Drug Designation Application (if applicable)",
                 "Apply for ODD if US prevalence <200,000. Provides 7yr market exclusivity, "
                 "50% tax credit on Phase 3 clinical costs, and waived PDUFA fees.",
                 "regulatory"))

    return sorted(ms, key=lambda x: x["iso_date"])


# ── Funding windows ───────────────────────────────────────────────────────────

def _funding_windows(product_type: str, start: date,
                      phase_ends: dict[str, date]) -> list[dict]:
    windows: list[dict] = []

    def _w(offset_months: int, name: str, amount: str, desc: str, url: str = "") -> dict:
        d = _add_months(start, offset_months)
        return {
            "date":        _fmt_date(d),
            "iso_date":    d.isoformat(),
            "name":        name,
            "amount":      amount,
            "type":        "funding",
            "description": desc,
            "url":         url,
            "action_required": True,
        }

    pre_ind_end_m = (phase_ends.get("preclinical", _add_months(start, 12)) - start).days // 30

    # Universal
    windows.append(_w(0,
        "NIH SBIR/STTR Phase I Application",
        "Up to $314,363",
        "Apply immediately: NIH SBIR Phase I for feasibility studies. "
        "Accepts rolling applications (omnibus due dates: Feb, June, Oct). "
        "Does NOT require prior data. First step in the non-dilutive funding ladder.",
        "https://grants.nih.gov/grants/funding/sbir.htm"))

    windows.append(_w(max(pre_ind_end_m - 6, 4),
        "NIH SBIR/STTR Phase II Application",
        "Up to $2.8M",
        "Apply after Phase I completion or bridge mechanism. "
        "Phase II funds IND-enabling and early clinical work. "
        "Strongest applications show clear commercial pathway and Phase I results.",
        "https://grants.nih.gov/grants/funding/sbir.htm"))

    # AMR-specific
    if "antibiotic" in product_type or "amr" in product_type:
        windows.append(_w(0,
            "CARB-X Application (Phase 1 window)",
            "Up to $4.5M Phase 1 + $12M Phase 2",
            "CARB-X funds novel mechanism antibiotics only. Application windows open twice yearly "
            "(typically March and September). Requires novel mechanism — not derivatives of existing classes. "
            "Does NOT fund Phase 3.",
            "https://carb-x.org/apply/"))
        windows.append(_w(max(pre_ind_end_m + 6, 12),
            "BARDA Broad Spectrum Antimicrobials BAA",
            "$50M–$200M",
            "BARDA funds late-stage AMR development. Requires prior Phase 1 safety data. "
            "Submit TechWatch pre-application 3 months before BAA opens. "
            "Frame as national security/biodefense asset.",
            "https://medicalcountermeasures.gov/barda/"))
        windows.append(_w(max(pre_ind_end_m, 10),
            "NIAID DMID Contract (AMR Priority Pathogen)",
            "$5M–$50M",
            "NIH NIAID Bacterial and Mycology Branch contracts for priority pathogens (MRSA, CRE, Acinetobacter). "
            "Monitor RFPs at niaid.nih.gov quarterly.",
            "https://www.niaid.nih.gov/research/dmid"))

    # Oncology
    if "oncology" in product_type or "cancer" in product_type:
        windows.append(_w(6,
            "NCI SBIR/STTR (Cancer-Focused)",
            "Up to $2M Phase I, $5M Phase II",
            "National Cancer Institute SBIR program has cancer-specific review panels "
            "and higher award caps. Apply through NIH SBIR omnibus mechanism.",
            "https://sbir.cancer.gov"))
        windows.append(_w(max(pre_ind_end_m - 3, 8),
            "NCI CRADA / Cooperative Agreement",
            "In-kind + $500K–$5M",
            "NCI Cooperative Research and Development Agreements provide in-kind NCI resources "
            "(preclinical, clinical) for promising oncology assets.",
            "https://www.cancer.gov/about-nci/organization/cco/research-programs"))

    # Gene/cell therapy
    if "gene" in product_type or "cell" in product_type:
        windows.append(_w(3,
            "NCATS Rare Diseases Program",
            "$500K–$3M",
            "NCATS funds therapeutic development for rare diseases. "
            "Apply via TRND (Therapeutics for Rare and Neglected Diseases) program.",
            "https://ncats.nih.gov/research/rare-diseases/trnd"))
        windows.append(_w(max(pre_ind_end_m, 8),
            "CIRM (California Institute for Regenerative Medicine)",
            "$5M–$20M",
            "CIRM funds clinical-stage cell and gene therapy trials. "
            "Requires California-based research component.",
            "https://www.cirm.ca.gov"))

    # Devices / diagnostics
    if product_type in ("medical_device", "diagnostic", "digital_health"):
        windows.append(_w(3,
            "NIBIB Small Business Program",
            "Up to $1.5M",
            "National Institute of Biomedical Imaging and Bioengineering SBIR for device and diagnostic innovation.",
            "https://www.nibib.nih.gov/research-funding/sbir-sttr"))
        windows.append(_w(6,
            "CMS Innovation Center (CMMI) Model Application",
            "Varies",
            "For devices/diagnostics with Medicare market, apply for CMMI model participation "
            "which can provide reimbursement pathway development funding.",
            "https://innovation.cms.gov"))

    return sorted(windows, key=lambda x: x["iso_date"])


# ── Strategic calendar ────────────────────────────────────────────────────────

def _strategic_calendar(product_type: str, disease: str, start: date,
                          phase_ends: dict[str, date]) -> list[dict]:
    events: list[dict] = []

    def _e(offset_months: int, event: str, desc: str, etype: str = "strategic") -> dict:
        d = _add_months(start, offset_months)
        return {"date": _fmt_date(d), "iso_date": d.isoformat(),
                "event": event, "type": etype, "description": desc}

    ph1_end_m = (phase_ends.get("phase1", _add_months(start, 27)) - start).days // 30
    ph2_end_m = (phase_ends.get("phase2", _add_months(start, 50)) - start).days // 30
    ph3_end_m = (phase_ends.get("phase3", _add_months(start, 82)) - start).days // 30

    events += [
        _e(0,  "IP Landscape Analysis", "Conduct freedom-to-operate (FTO) and patentability analysis. "
                "File provisional patent(s) before any public disclosure. "
                "Target 20+ claims; file continuation strategy with IP counsel."),
        _e(1,  "KOL Identification & Advisory Board Formation",
                "Identify 3-5 key opinion leaders in the disease space. "
                "Invite to scientific advisory board. Their clinical validation "
                "will be critical for payor access and AdCom preparation."),
        _e(3,  "Competitive Intelligence Refresh",
                "Subscribe to clinical trial alerts for your indication. "
                "Review competitor pipeline quarterly. Update differentiation narrative."),
        _e(max(ph1_end_m - 12, 6),
                "Series A Fundraising Preparation",
                "With Phase 1 safety data in hand, prepare investor deck "
                "with Phase 2 design, biomarker strategy, and partnership thesis. "
                "Target milestone-anchored raise: Phase 2 completion + EoP2."),
        _e(ph2_end_m - 6,
                "Partnership / Licensing Outreach",
                "Initiate business development conversations with large pharma. "
                "Phase 2 data readout is the optimal time: risk reduced, Phase 3 cost high. "
                "Prepare data room and non-confidential deck."),
        _e(ph2_end_m + 3,
                "Series B / Pivotal Financing",
                "Phase 3 requires Series B or partnering. With EoP2 alignment, "
                "raise to fund Phase 3 + NDA preparation. Target 24-month runway post-close."),
        _e(ph3_end_m - 6,
                "Reimbursement & Market Access Strategy",
                "Engage health economic consultants. Develop HEOR dossier for "
                "FDA label claims + payor value proposition. "
                "File for J-code (biologics) or Q-code (devices) 18 months pre-launch."),
        _e(ph3_end_m + 2,
                "Commercial Launch Preparation",
                "Hire VP Commercial, VP Medical Affairs. Begin HCP education programs. "
                "Negotiate GPO/formulary contracts. Set up specialty pharmacy (if required). "
                "Prepare for FDA Advisory Committee meeting if applicable."),
    ]

    return sorted(events, key=lambda x: x["iso_date"])


# ── Core timeline builder ─────────────────────────────────────────────────────

_MODALITY_MAP = {
    "antibiotic":          "drug_small_molecule",
    "orphan_drug":         "drug_small_molecule",
    "oncology_drug":       "drug_small_molecule",
    "gene_therapy":        "gene_cell_therapy",
    "medical_device":      "medical_device",
    "software":            "digital_health",
    "diagnostic":          "diagnostic",
    "other":               "drug_small_molecule",
}

_LOA_BY_PHASE = {
    "preclinical": "~10%",
    "phase1":      "~14%",
    "phase2":      "~29%",
    "phase3":      "~58%",
    "filed":       "~85%",
}

_KEY_RISKS = {
    "drug_small_molecule": [
        "Phase 2 efficacy signal may not replicate in larger Phase 3 (false discovery)",
        "Clinical hold risk: safety signals in Phase 1 can delay programme by 12-18 months",
        "CMC: manufacturing process changes require bridging studies that add 6-12 months",
        "Payor rejection: without HEOR data, payers may not reimburse at target price",
    ],
    "gene_cell_therapy": [
        "Manufacturing scale-up: viral vector yield and purity failures delay IND by 12-24 months",
        "Long-term safety surveillance required (15yr per FDA GT guidance) — ongoing cost post-approval",
        "One-time pricing model faces payer resistance; outcomes-based contracts complex to structure",
        "Immunogenicity and re-dosing limitations may restrict addressable population",
    ],
    "medical_device": [
        "510(k) predicate rejection triggers De Novo or PMA pathway, adding 12-24 months",
        "Post-market surveillance requirements can be extensive for Class III devices",
        "Physician training and learning curve delays commercial adoption",
        "Reimbursement coding (CPT/HCPCS) may lag approval by 12-18 months",
    ],
    "diagnostic": [
        "CLIA waiver studies add 6-12 months post-clearance",
        "Lab Information System (LIS) integration delays commercial rollout",
        "Reimbursement coding (CPT) lag means revenue delayed 12-18 months post-clearance",
    ],
}


def generate_timeline(
    idea: str,
    product_type: str,
    pi_report: Optional[dict] = None,
    disease_name: Optional[str] = None,
    start_date: Optional[date] = None,
) -> dict:
    """
    Generate a full development timeline from an idea + product type.

    If pi_report is provided (from the alignment service), uses its clinical_trial_requirements
    and regulatory_pathway to set exact phase durations.
    Otherwise uses canonical template values.

    Returns a serialisable dict matching DevelopmentTimeline structure.
    """
    if start_date is None:
        from datetime import date as _date
        start_date = _date.today()

    pt = _MODALITY_MAP.get(product_type.lower(), "drug_small_molecule")

    # Extract durations from PIReport if available
    phase_durations: dict[str, int] = {}
    if pi_report and "regulatory_pathway" in pi_report:
        trials = pi_report["regulatory_pathway"].get("clinical_trial_requirements", [])
        for t in trials:
            phase = t.get("phase", "").lower().replace(" ", "")
            dur_str = t.get("duration", "")
            # Parse "12-18 months" → midpoint
            nums = [int(x) for x in dur_str.split() if x.isdigit()]
            if nums:
                phase_durations[phase] = sum(nums) // len(nums)

    def _dur(key: str, default: int) -> int:
        return phase_durations.get(key, default)

    # Phase template lookup
    tmpl_pre  = _PRECLINICAL.get(pt, _PRECLINICAL["other"])
    tmpl_ph1  = _PHASE1.get(pt, _PHASE1["other"])
    tmpl_ph2  = _PHASE2.get(pt, _PHASE2["other"])
    tmpl_ph3  = _PHASE3.get(pt, _PHASE3["other"])
    tmpl_sub  = _SUBMISSION.get(pt, _SUBMISSION["other"])
    tmpl_rev  = _REVIEW.get(pt, _REVIEW["other"])

    # Build phases in sequence
    phases = []
    phase_ends: dict[str, date] = {}
    cursor = start_date

    def _build_phase(phase_id: str, name: str, ptype: str, template: tuple,
                     override_months: int = 0) -> dict:
        nonlocal cursor
        months     = override_months or template[0]
        cost_lo    = template[1] * 1_000_000
        cost_hi    = template[2] * 1_000_000
        activities = template[3]
        start      = cursor
        end        = _add_months(cursor, months)
        cursor     = end
        phase_ends[phase_id] = end
        return asdict(TimelinePhase(
            id=phase_id, name=name, type=ptype,
            start_date=_fmt_date(start), end_date=_fmt_date(end),
            start_iso=start.isoformat(), end_iso=end.isoformat(),
            duration_months=months,
            cost_low_usd=cost_lo, cost_high_usd=cost_hi,
            cost_fmt=f"${template[1]}–{template[2]}M",
            key_activities=activities,
            milestones=[],
            color=_PHASE_COLORS.get(ptype, "#6366f1"),
        ))

    phases.append(_build_phase("preclinical", "IND-Enabling / Preclinical", "preclinical", tmpl_pre,
                                _dur("preclinical", 0)))
    phases.append(_build_phase("phase1", "Phase 1 — Safety & Pharmacokinetics", "phase1", tmpl_ph1,
                                _dur("phase1", 0)))

    # Skip Phase 2/3 for devices/diagnostics (different structure)
    if pt not in ("medical_device", "diagnostic"):
        phases.append(_build_phase("phase2", "Phase 2 — Proof of Concept", "phase2", tmpl_ph2,
                                    _dur("phase2", 0)))
        phases.append(_build_phase("phase3", "Phase 3 — Pivotal Registration", "phase3", tmpl_ph3,
                                    _dur("phase3", 0)))
    else:
        phases.append(_build_phase("phase2", "Pivotal Study Design & Execution", "phase2", tmpl_ph2))

    phases.append(_build_phase("submission", "NDA/BLA/510(k) Preparation & Submission", "submission", tmpl_sub))
    phases.append(_build_phase("review",     "FDA Review & Approval", "review", tmpl_rev))

    approval_date = cursor
    total_months  = (approval_date - start_date).days // 30
    total_years   = round(total_months / 12, 1)

    # Cost totals
    total_lo = sum(p["cost_low_usd"]  for p in phases)
    total_hi = sum(p["cost_high_usd"] for p in phases)
    total_lo_m = total_lo // 1_000_000
    total_hi_m = total_hi // 1_000_000

    # Milestones, funding, strategic calendar
    reg_ms    = _regulatory_milestones(product_type, start_date, phase_ends)
    funding   = _funding_windows(product_type, start_date, phase_ends)
    strategic = _strategic_calendar(product_type, disease_name or "your indication",
                                     start_date, phase_ends)

    # Key risks
    risks = _KEY_RISKS.get(pt, _KEY_RISKS["drug_small_molecule"])

    from datetime import datetime
    return {
        "product_type":            product_type,
        "disease":                 disease_name or idea[:80],
        "idea_submitted":          idea[:200],
        "start_date":              _fmt_date(start_date),
        "start_iso":               start_date.isoformat(),
        "estimated_approval_date": _quarter(approval_date),
        "estimated_approval_iso":  approval_date.isoformat(),
        "total_duration_years":    total_years,
        "total_cost_low_usd":      total_lo,
        "total_cost_high_usd":     total_hi,
        "total_cost_fmt":          f"${total_lo_m}–${total_hi_m}M",
        "phases":                  phases,
        "regulatory_milestones":   reg_ms,
        "funding_windows":         funding,
        "strategic_calendar":      strategic,
        "probability_of_approval": _LOA_BY_PHASE.get("phase1", "~10%"),
        "key_risks":               risks,
        "generated_at":            datetime.utcnow().isoformat() + "Z",
    }
