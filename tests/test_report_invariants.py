"""
Report Invariants — v3 Spec A.1
================================
Regression harness for the Hublink product (research data infrastructure, LIFE_SCIENCES_RESEARCH).
Every defect in v3 spec becomes a test here before it becomes a fix.

Test classes:
  TestBannedTokensStatic     — banned tokens must not appear in static prompts/templates
  TestBannedTokensFixture    — banned tokens must not appear in a saved report fixture
  TestStrategyPlaybookGate   — §4 playbook must never emit clinical content for research domain
  TestMarketModelShape       — §2 numbers must reconcile and be domain-appropriate
  TestBrandingLintRuntime    — Project Elevate / Expert model: must not appear in report output
  TestMidwordTruncation      — no mid-word truncated strings in report
  TestDeterminism            — numeric fields must not vary across runs (slow, requires API key)

Run fast tests (no API):  pytest tests/test_report_invariants.py -m "not slow"
Run all:                   pytest tests/test_report_invariants.py
"""

from __future__ import annotations

import json
import os
import re
import pytest
from pathlib import Path

# ── paths ─────────────────────────────────────────────────────────────────────

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hublink.json"
_APP_ROOT     = Path(__file__).parent.parent / "app"

with open(_FIXTURE_PATH) as _f:
    _HUB_FIXTURE = json.load(_f)

_HUBLINK_IDEA   = _HUB_FIXTURE["idea"]
_BANNED_TOKENS  = _HUB_FIXTURE["banned_tokens_research_domain"]
_NUMERIC_FIELDS = _HUB_FIXTURE["numeric_fields_must_be_stable"]

# Mid-word truncation: a word ending in a non-terminal character (not space/punct/newline)
# that is followed by nothing — i.e. a string that was cut at a non-boundary.
# Pattern: ≥3 word chars, then a letter/digit with no following space or boundary.
_MIDWORD_RE = re.compile(r'\b\w{3,}[a-zA-Z]$', re.MULTILINE)

# ── helpers ───────────────────────────────────────────────────────────────────

def _py_files_under(root: Path):
    for p in root.rglob("*.py"):
        if ".venv" not in str(p) and "__pycache__" not in str(p):
            yield p


def _text(path) -> str:
    try:
        return Path(path).read_text(errors="replace")
    except Exception:
        return ""


def _all_strings_in_report(report: dict) -> list[str]:
    """Recursively collect all string leaf values from a report dict."""
    out = []
    def _walk(obj):
        if isinstance(obj, str):
            out.append(obj)
        elif isinstance(obj, dict):
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)
    _walk(report)
    return out


# ═══════════════════════════════════════════════════════════════════════════════
# 1 — Banned tokens: static sources (no API, always runs)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBannedTokensStatic:
    """
    Banned clinical vocabulary must not appear in STATIC prompt templates.
    These are the strings that get injected into every research-domain report
    regardless of what Claude generates.
    """

    @pytest.mark.parametrize("token", ["NTAP", "CPT 99", "J-code", "DRG", "WAC", "DALY",
                                        "Breakthrough Device", "PCCP"])
    def test_research_tool_system_prompt_does_not_contain_banned_token(self, token):
        path = _APP_ROOT / "services" / "expert_profiles_v2.py"
        text = _text(path)
        # Find the research tool system prompt section
        match = re.search(
            r'class ResearchToolExpert.*?system_prompt\s*=\s*"""(.*?)"""',
            text, re.DOTALL,
        )
        if not match:
            pytest.skip("ResearchToolExpert system_prompt not found (structure changed)")
        prompt_body = match.group(1)
        # The token should only appear in the CRITIC RULES ban list, not in the prompt body
        assert token not in prompt_body or "BANNED" in prompt_body.upper(), (
            f"Token '{token}' must not appear in ResearchToolExpert system_prompt body "
            f"(only in BANNED VOCABULARY list)"
        )

    def test_strategy_database_research_entries_exist(self):
        from app.services.strategy_database import DOMAIN_SPECIFIC_STRATEGIES
        assert "research_infrastructure_saas" in DOMAIN_SPECIFIC_STRATEGIES, \
            "strategy_database must have 'research_infrastructure_saas' entry"
        assert "research_tool_non_clinical" in DOMAIN_SPECIFIC_STRATEGIES, \
            "strategy_database must have 'research_tool_non_clinical' entry"

    def test_strategy_database_research_entries_contain_no_clinical_vocabulary(self):
        from app.services.strategy_database import DOMAIN_SPECIFIC_STRATEGIES
        clinical_vocab = {"NTAP", "CPT 99", "J-code", "DRG", "WAC", "formulary", "Livongo", "Viz.ai"}
        for key in ("research_infrastructure_saas", "research_tool_non_clinical"):
            strategies = DOMAIN_SPECIFIC_STRATEGIES.get(key, [])
            all_text = json.dumps(strategies).lower()
            for vocab in clinical_vocab:
                assert vocab.lower() not in all_text, (
                    f"strategy_database['{key}'] must not contain '{vocab}' — "
                    f"clinical vocabulary leaks into §4 for research-domain products"
                )

    def test_domain_gate_exists_in_alignment_service(self):
        """alignment_service must override sub_expert_id for LIFE_SCIENCES_RESEARCH domain."""
        text = _text(_APP_ROOT / "services" / "alignment_service.py")
        # The gate must be a direct assignment in the same if-block — look for it per line
        found = any(
            "LIFE_SCIENCES_RESEARCH" in line and "research_infrastructure_saas" in line
            for pair in zip(text.splitlines(), text.splitlines()[1:])
            for line in pair
            if "LIFE_SCIENCES_RESEARCH" in pair[0] or "research_infrastructure_saas" in pair[0]
        )
        # Fallback: scan for the pattern within a 10-line window
        if not found:
            lines = text.splitlines()
            for i, ln in enumerate(lines):
                if "LIFE_SCIENCES_RESEARCH" in ln:
                    window = "\n".join(lines[i:i+10])
                    if "research_infrastructure_saas" in window:
                        found = True
                        break
        assert found, (
            "alignment_service.py must contain a domain gate close to LIFE_SCIENCES_RESEARCH check: "
            "'_sub_id = research_infrastructure_saas'"
        )

    def test_alignment_service_bans_project_elevate_as_source(self):
        text = _text(_APP_ROOT / "services" / "alignment_service.py")
        assert "Project Elevate" in text, \
            "alignment_service.py must explicitly ban 'Project Elevate' as a source label"

    def test_alignment_service_bans_expert_model_prefix(self):
        text = _text(_APP_ROOT / "services" / "alignment_service.py")
        lower = text.lower()
        assert "expert model:" in lower or "expert domain knowledge" in lower, (
            "alignment_service.py must explicitly ban 'Expert model:' / 'Expert Domain Knowledge' labels"
        )

    def test_frontend_market_intro_not_hardcoded_pharma(self):
        """app.html §2 intro must not contain hardcoded drug-domain prose."""
        html_path = Path(__file__).parent.parent.parent / "ProjectElevate-Frontend" / "app.html"
        if not html_path.exists():
            pytest.skip("Frontend app.html not found at expected path")
        text = html_path.read_text(errors="replace")
        assert "assuming 100% patient capture" not in text, (
            "Frontend app.html must not contain 'assuming 100% patient capture' — "
            "this hardcoded pharma prose was rendered verbatim for research-domain products (B-01)"
        )
        assert "formulary access, competitive share, and geographic concentration" not in text, (
            "Frontend app.html must not contain hardcoded pharma §2 intro prose (B-01)"
        )
        assert "primary epidemiological sources" not in text, (
            "Frontend app.html must not contain 'primary epidemiological sources' as hardcoded text (B-01)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 2 — Strategy playbook gate (no API, always runs)
# ═══════════════════════════════════════════════════════════════════════════════

class TestStrategyPlaybookGate:
    """
    §4 strategic playbook must return research-domain content when
    sub_expert_id is forced to research_infrastructure_saas.
    Clinial vocabulary (NTAP, CPT, Livongo, Viz.ai, stroke, diabetes)
    must never appear.
    """

    def test_research_playbook_has_no_ntap(self):
        from app.services.strategy_database import format_strategies_for_report
        playbook = format_strategies_for_report("research_infrastructure_saas")
        text = json.dumps(playbook).lower()
        for tok in ("ntap", "cpt 99", "j-code", "drg", "livongo", "viz.ai"):
            assert tok not in text, (
                f"research_infrastructure_saas playbook must not contain '{tok}' — "
                f"clinical vocabulary leaked into §4"
            )

    def test_research_playbook_mentions_academic_pi(self):
        from app.services.strategy_database import format_strategies_for_report
        playbook = format_strategies_for_report("research_infrastructure_saas")
        text = json.dumps(playbook).lower()
        assert any(kw in text for kw in ("pi", "academic", "lab", "university", "grant", "sbir")), (
            "research_infrastructure_saas playbook must reference academic PI / university / grant context"
        )

    def test_digital_rpm_playbook_has_clinical_vocab(self):
        """Confirm the RPM playbook DOES have clinical vocab — so we know the gate matters."""
        from app.services.strategy_database import format_strategies_for_report
        rpm_playbook = format_strategies_for_report("digital_rpm")
        text = json.dumps(rpm_playbook).lower()
        has_clinical = any(tok in text for tok in ("cpt", "ntap", "livongo", "rpm"))
        assert has_clinical, (
            "digital_rpm playbook must contain clinical vocab (CPT/NTAP/Livongo) — "
            "if it doesn't, this test needs updating but the domain gate is still needed"
        )

    def test_format_strategies_returns_list(self):
        from app.services.strategy_database import format_strategies_for_report
        for sid in ("research_infrastructure_saas", "research_tool_non_clinical",
                    "drug_amr", "digital_rpm", "device_cardiovascular"):
            result = format_strategies_for_report(sid)
            assert isinstance(result, list), f"format_strategies_for_report('{sid}') must return a list"
            assert len(result) >= 1, f"format_strategies_for_report('{sid}') must return ≥1 strategy"


# ═══════════════════════════════════════════════════════════════════════════════
# 3 — Market model shape (no API, tests structural assertions)
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketModelShape:
    """
    For a research-domain product, the market sizing derivation must:
    - Use labs as the unit, not hospitals
    - Produce a TAM in the $1M–$75M range (not $375M)
    - Reconcile SAM = TAM × gate, SOM = SAM × gate
    """

    def _run_derivation(self):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
        return generate_market_sizing_derivation(
            idea=_HUBLINK_IDEA,
            disease_name="neuroscience research data logging",
            therapeutic_area="other",
            sub_expert_id="research_tool_non_clinical",
        )

    def test_research_tool_derivation_produces_lab_unit(self):
        result = self._run_derivation()
        # Unit should be labs/PIs, not hospitals — check formula_name or steps
        text = (result.formula_name + result.formula_overview).lower()
        assert "lab" in text or "pi" in text or "researcher" in text, (
            "research_tool_non_clinical derivation must reference 'lab' or 'PI' in its formula, "
            "not hospitals — TAM formula error (H-07)"
        )

    def test_research_tool_tam_is_not_375m(self):
        result = self._run_derivation()
        tam = result.us_tam_usd
        assert tam < 75_000_000, (
            f"research_tool TAM is ${tam:,.0f} — must be < $75M. "
            f"$375M indicates the hospital-SaaS template is still running (H-07/B-03)"
        )
        assert tam > 1_000_000, (
            f"research_tool TAM is ${tam:,.0f} — implausibly small, check derivation"
        )

    def test_sam_is_fraction_of_tam(self):
        result = self._run_derivation()
        tam = result.us_tam_usd
        sam = result.us_sam_usd
        if tam > 0 and sam > 0:
            ratio = sam / tam
            assert 0.10 <= ratio <= 0.60, (
                f"SAM/TAM ratio is {ratio:.1%} — expected 10%–60% for a research tool. "
                f"TAM={tam:,.0f}, SAM={sam:,.0f}"
            )

    def test_som_is_fraction_of_sam(self):
        result = self._run_derivation()
        sam = result.us_sam_usd
        som = result.us_som_usd
        if sam and som:
            ratio = som / sam
            assert 0.05 <= ratio <= 0.40, (
                f"SOM/SAM ratio is {ratio:.1%} — expected 5%–40%. "
                f"SAM={sam:,.0f}, SOM={som:,.0f}"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 4 — Branding lint: static source tree (no API)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBrandingLintStatic:
    """
    'Project Elevate System Context' and 'RPM Expert Domain Knowledge' must not
    appear as compound fabricated source names in any system prompt or knowledge file.
    These are the strings the LLM echoes verbatim into §1 citations.
    """

    _COMPOUND_PATTERNS = [
        r"RPM Expert Domain Knowledge\s*[-–]\s*",
        r"Project Elevate\s+(System\s+Context|RPM\s+Context|Knowledge\s+Base)",
        r"(Medlevate|Elevate)\s+RPM\s+Context\s+20\d\d",
        r"Expert Domain Knowledge\s*[-–]\s*\w+\s+Context",
    ]

    @pytest.mark.parametrize("fname", [
        "expert_profiles.py",
        "expert_profiles_v2.py",
        "alignment_service.py",
        "knowledge_retriever.py",
        "retrieval_pipeline.py",
    ])
    def test_no_compound_fabricated_source_in_prompt_file(self, fname):
        path = _APP_ROOT / "services" / fname
        if not path.exists():
            pytest.skip(f"{fname} not found")
        text = _text(path)
        hits = []
        for pat in self._COMPOUND_PATTERNS:
            for m in re.finditer(pat, text, re.I):
                hits.append(m.group(0))
        assert hits == [], (
            f"{fname} contains compound fabricated source-name pattern(s): {hits!r}. "
            "These strings get echoed verbatim into §1 citations by the LLM."
        )

    def test_citation_validator_covers_project_elevate(self):
        from app.services.citation_validator import INTERNAL_KB_PATTERNS
        assert any("project elevate" in p.lower() or "elevate" in p.lower()
                   for p in INTERNAL_KB_PATTERNS), (
            "citation_validator.INTERNAL_KB_PATTERNS must cover 'Project Elevate'"
        )

    def test_citation_validator_covers_rpm_context(self):
        from app.services.citation_validator import INTERNAL_KB_PATTERNS
        assert any("rpm" in p.lower() or "rpm context" in p.lower()
                   for p in INTERNAL_KB_PATTERNS), (
            "citation_validator.INTERNAL_KB_PATTERNS must cover 'RPM Context'"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 5 — Fixture-based tests (run against a saved report dict)
# These load tests/fixtures/hublink_report.json if it exists; skip otherwise.
# To populate: save the output of a live run as JSON at that path.
# ═══════════════════════════════════════════════════════════════════════════════

_SAVED_REPORT_PATH = Path(__file__).parent / "fixtures" / "hublink_report.json"


@pytest.fixture(scope="module")
def hublink_report():
    if not _SAVED_REPORT_PATH.exists():
        pytest.skip(
            "tests/fixtures/hublink_report.json not found — "
            "run a live Hublink report and save it there to enable fixture tests"
        )
    with open(_SAVED_REPORT_PATH) as f:
        return json.load(f)


class TestBannedTokensFixture:
    """Banned tokens must not appear in a saved Hublink report output."""

    @pytest.mark.parametrize("token", _BANNED_TOKENS)
    def test_token_absent_from_report(self, hublink_report, token):
        all_text = " ".join(_all_strings_in_report(hublink_report))
        assert token not in all_text, (
            f"Banned token '{token}' found in Hublink report output. "
            f"This token is forbidden for LIFE_SCIENCES_RESEARCH domain."
        )

    def test_no_project_elevate_in_citations(self, hublink_report):
        citations = hublink_report.get("literature_citations", [])
        for cit in citations:
            src = cit.get("source", "") or cit.get("source_name", "")
            assert "Project Elevate" not in src, (
                f"Citation source contains 'Project Elevate': {src!r} — "
                "internal label leaked into §1 bibliography"
            )

    def test_no_expert_model_label_in_report(self, hublink_report):
        all_text = " ".join(_all_strings_in_report(hublink_report))
        assert "Expert model:" not in all_text, (
            "'Expert model:' prefix must not appear in any report field — "
            "it is an internal routing label, not a user-facing string"
        )


class TestMidwordTruncation:
    """No string in the report must end mid-word."""

    def test_no_midword_truncation_in_report(self, hublink_report):
        truncated = []
        for s in _all_strings_in_report(hublink_report):
            if len(s) > 40 and _MIDWORD_RE.search(s.rstrip()):
                truncated.append(s[-60:])
        assert not truncated, (
            f"Mid-word truncation found in {len(truncated)} string(s): {truncated[:3]}"
        )


class TestMarketReconciliation:
    """§2 numbers must be internally consistent across all rendered instances."""

    def test_tam_and_sam_reconcile(self, hublink_report):
        ms = hublink_report.get("market_sizing", {})
        tam = ms.get("total_addressable_market_usd", 0)
        sam = ms.get("serviceable_market_usd", 0)
        if tam and sam:
            assert sam <= tam, f"SAM ({sam:,.0f}) must not exceed TAM ({tam:,.0f})"
            ratio = sam / tam
            assert 0.10 <= ratio <= 0.60, (
                f"SAM/TAM = {ratio:.1%} — outside expected 10%–60% range for research tool"
            )

    def test_tam_is_not_375m(self, hublink_report):
        ms = hublink_report.get("market_sizing", {})
        tam = ms.get("total_addressable_market_usd", 0)
        assert tam < 75_000_000, (
            f"Hublink TAM is ${tam/1e6:.1f}M — still using hospital-SaaS template. "
            f"Expected < $75M for a research-tool product."
        )

    def test_competitive_section_names_status_quo(self, hublink_report):
        comp = hublink_report.get("competitive_landscape", {})
        comp_text = json.dumps(comp).lower()
        has_status_quo = (
            "manual" in comp_text or "sd card" in comp_text or
            "sd-card" in comp_text or "status quo" in comp_text or
            "diy" in comp_text or "grad student" in comp_text
        )
        assert has_status_quo, (
            "Competitive section must name status quo / manual SD-card retrieval "
            "as the primary incumbent (B-07)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 6 — Numeric determinism (slow, requires API key, skipped in fast CI)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.slow
class TestNumericDeterminism:
    """
    Run the market sizing derivation 5× with the same input, same seed.
    All numeric fields must produce identical values.
    This test requires the Anthropic API key to be set.
    """

    def test_market_sizing_derivation_is_deterministic(self):
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation as derive_market_sizing
        results = []
        for _ in range(5):
            r = derive_market_sizing(
                idea=_HUBLINK_IDEA,
                disease_name="neuroscience research data logging",
                therapeutic_area="other",
                sub_expert_id="research_tool_non_clinical",
            )
            results.append({
                "tam": r.us_tam_usd,
                "sam": r.us_sam_usd,
            })
        tams = {r["tam"] for r in results}
        sams = {r["sam"] for r in results}
        assert len(tams) == 1, (
            f"TAM varied across 5 runs: {tams}. "
            f"market_sizing_derivation must be deterministic for research tools."
        )
        assert len(sams) == 1, (
            f"SAM varied across 5 runs: {sams}."
        )

    def test_non_medical_product_gets_different_tam(self):
        """
        A.2 diagnostic: a soil-moisture sensor must not produce $375M TAM.
        If it does, the market engine is a static template.
        """
        from app.services.market_sizing_derivation_service import generate_market_sizing_derivation as derive_market_sizing
        agri_idea = (
            "A soil-moisture sensor network for precision agriculture. "
            "Wireless sensors measure volumetric water content and relay data "
            "to a cloud dashboard for irrigation scheduling. "
            "No medical claims. Sold to commercial farms."
        )
        result = derive_market_sizing(
            idea=agri_idea,
            disease_name="",
            therapeutic_area="other",
            sub_expert_id="research_tool_non_clinical",
        )
        tam = result.us_tam_usd
        assert tam != 375_000_000, (
            "Non-medical product (soil sensor) produced TAM=$375M — "
            "the market engine is returning a static template regardless of input (A.2 diagnostic)"
        )


# ── C.1 / C.2: Product classifier + conditioned questions ────────────────────

class TestProductClassifier:
    """
    Spec v3 C.1: Stage-1 product classifier must resolve domain + archetype
    deterministically (no LLM for those fields) and return a valid Classification.

    Spec v3 C.2: Every IntakeQuestion must have a non-empty binds_to field.
    """

    _HUBLINK_IDEA = (
        "Hublink is a research data infrastructure platform for academic neuroscience labs. "
        "It automates wireless data retrieval from wearable sensors (accelerometers, ECG) "
        "using Bluetooth Low Energy, replacing manual SD-card extraction. "
        "Sold to academic PIs and core facilities at research universities. "
        "No patient care, no diagnostic claims. NIH-funded researchers."
    )

    _DRUG_IDEA = (
        "DrugX is a novel small molecule antibiotic targeting CRE/NDM-1 producing organisms "
        "in ICU patients with carbapenem-resistant infections. Phase 1 safety data confirmed. "
        "Seeking QIDP designation. Buyer is hospital P&T committee."
    )

    def test_research_product_domain(self):
        """C.1: Research product must resolve to LIFE_SCIENCES_RESEARCH domain."""
        from app.services.product_classifier import _resolve_domain_and_archetype
        domain, arch = _resolve_domain_and_archetype(self._HUBLINK_IDEA)
        assert domain == "LIFE_SCIENCES_RESEARCH", (
            f"Hublink resolved to domain={domain!r} — expected LIFE_SCIENCES_RESEARCH. "
            "soft_router or pattern matching may have regressed."
        )

    def test_research_product_archetype(self):
        """C.1: Research product must resolve to a research archetype string."""
        from app.services.product_classifier import _resolve_domain_and_archetype
        _, arch = _resolve_domain_and_archetype(self._HUBLINK_IDEA)
        assert "research" in arch.lower(), (
            f"Hublink resolved to archetype={arch!r} — expected a research archetype."
        )

    def test_drug_product_domain(self):
        """C.1: Drug product must resolve to LIFE_SCIENCES_CLINICAL domain."""
        from app.services.product_classifier import _resolve_domain_and_archetype
        domain, arch = _resolve_domain_and_archetype(self._DRUG_IDEA)
        assert domain == "LIFE_SCIENCES_CLINICAL", (
            f"Drug product resolved to domain={domain!r} — expected LIFE_SCIENCES_CLINICAL."
        )

    def test_research_conditioned_questions_all_have_binds_to(self):
        """C.2: Every question returned for a research product must have a binds_to field."""
        from app.services.product_classifier import Classification, get_conditioned_questions, questions_to_legacy_format
        cls = Classification(
            product_name="Hublink",
            one_line="Test.",
            domain="LIFE_SCIENCES_RESEARCH",
            archetype="research_infrastructure_saas",
            trl=5,
            confidence=0.8,
            ambiguities=[],
        )
        questions = questions_to_legacy_format(get_conditioned_questions(cls))
        for q in questions:
            assert q.get("binds_to"), (
                f"Question {q.get('field')!r} has no binds_to — violates spec C.2 hard rule. "
                "Every IntakeQuestion must bind to a named model field."
            )

    def test_drug_conditioned_questions_all_have_binds_to(self):
        """C.2: Every question returned for a drug product must have a binds_to field."""
        from app.services.product_classifier import Classification, get_conditioned_questions, questions_to_legacy_format
        cls = Classification(
            product_name="DrugX",
            one_line="Test.",
            domain="LIFE_SCIENCES_CLINICAL",
            archetype="therapeutic_small_molecule",
            trl=4,
            confidence=0.75,
            ambiguities=[],
        )
        questions = questions_to_legacy_format(get_conditioned_questions(cls))
        for q in questions:
            assert q.get("binds_to"), (
                f"Question {q.get('field')!r} has no binds_to — violates spec C.2 hard rule."
            )

    def test_research_questions_not_clinical_flavoured(self):
        """C.2: Research product questions must not contain drug/clinical vocabulary."""
        from app.services.product_classifier import Classification, get_conditioned_questions
        cls = Classification(
            product_name="Hublink",
            one_line="Test.",
            domain="LIFE_SCIENCES_RESEARCH",
            archetype="research_infrastructure_saas",
            trl=5,
            confidence=0.8,
            ambiguities=[],
        )
        clinical_vocab = {"formulary", "ntap", "cpt", "line of therapy", "payer", "p&t committee"}
        for q in get_conditioned_questions(cls):
            combined = (q.text + " " + (q.why_asked or "")).lower()
            hits = [v for v in clinical_vocab if v in combined]
            assert not hits, (
                f"Research question {q.id!r} contains clinical vocab {hits} — "
                "conditioned questions must not bleed clinical vocabulary into research archetype."
            )

    def test_product_name_extraction_heuristic(self):
        """C.1 fallback: heuristic must pull 'Hublink' from 'Hublink is a ...' pattern."""
        from app.services.product_classifier import _extract_product_name_heuristic
        name = _extract_product_name_heuristic("Hublink is a research data infrastructure platform for academic labs.")
        assert name == "Hublink", f"Heuristic returned {name!r} — expected 'Hublink'."

    def test_classification_fields_are_complete(self):
        """C.1: Classification object must have all required fields populated."""
        from unittest.mock import patch
        from app.services.product_classifier import classify_product
        with patch("app.services.product_classifier._llm_extract", return_value={
            "product_name": "Hublink",
            "one_line": "Automates wireless sensor data retrieval for NIH-funded neuroscience PIs.",
            "trl": 5,
            "ambiguities": ["Price per lab?", "Number of target labs?"],
        }):
            cls = classify_product(self._HUBLINK_IDEA)
        assert cls.product_name == "Hublink"
        assert cls.domain == "LIFE_SCIENCES_RESEARCH"
        assert cls.trl == 5
        assert len(cls.ambiguities) == 2
        assert 0.0 < cls.confidence <= 1.0
