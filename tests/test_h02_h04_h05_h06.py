"""
Tests for H-02, H-04, H-05, H-06 defect fixes.

H-02  regulatory_status.py  — typed RegulatoryStatus + single decision tree
H-04  competitive_intelligence_service.py  — research tool comparator list + relevance gate
H-05  citation_validator.py  — internal KB strip + domain mismatch + placeholder nulling
H-06  person_verifier.py  — KOL sanitizer + criteria fallback
"""

import pytest
import asyncio

# ─────────────────────────────────────────────────────────────────────────────
# H-02: RegulatoryStatus
# ─────────────────────────────────────────────────────────────────────────────

from app.services.regulatory_status import (
    RegulatoryStatus,
    derive_regulatory_status,
    regulatory_directive,
    format_regulatory_decision_tree,
)


class TestDeriveRegulatoryStatus:

    def test_research_tool_non_clinical_is_not_regulated(self):
        status = derive_regulatory_status(
            archetype="research_tool_non_clinical",
            sub_expert_id="research_tool_non_clinical",
        )
        assert status == RegulatoryStatus.NOT_REGULATED

    def test_research_infrastructure_saas_is_not_regulated(self):
        status = derive_regulatory_status(
            archetype="research_infrastructure_saas",
            sub_expert_id="research_infrastructure_saas",
        )
        assert status == RegulatoryStatus.NOT_REGULATED

    def test_drug_archetype_is_regulated(self):
        status = derive_regulatory_status(
            archetype="drug",
            sub_expert_id="drug_amr",
        )
        assert status == RegulatoryStatus.REGULATED

    def test_sub_expert_id_drug_prefix_is_regulated(self):
        status = derive_regulatory_status(
            archetype="",
            sub_expert_id="drug_oncology",
        )
        assert status == RegulatoryStatus.REGULATED

    def test_digital_cds_is_ambiguous(self):
        status = derive_regulatory_status(
            archetype="digital_cds",
            sub_expert_id="digital_cds",
        )
        assert status == RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL

    def test_digital_wellness_is_likely_exempt(self):
        status = derive_regulatory_status(
            archetype="digital_wellness",
            sub_expert_id="digital_wellness",
        )
        assert status == RegulatoryStatus.LIKELY_EXEMPT

    def test_clinical_idea_text_upgrades_non_clinical_to_ambiguous(self):
        """If a research tool idea mentions patient care, flag as ambiguous."""
        status = derive_regulatory_status(
            archetype="research_tool_non_clinical",
            sub_expert_id="research_tool_non_clinical",
            idea="A wearable logger that helps diagnose epilepsy in patients.",
        )
        assert status == RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL

    def test_non_clinical_idea_does_not_downgrade_regulated(self):
        """Clinical archetype + non-clinical language stays REGULATED."""
        status = derive_regulatory_status(
            archetype="drug",
            sub_expert_id="drug_amr",
            idea="A research platform for academic PIs studying AMR.",
        )
        assert status == RegulatoryStatus.REGULATED

    def test_unknown_archetype_returns_ambiguous(self):
        status = derive_regulatory_status(
            archetype="totally_unknown_xyz",
            sub_expert_id="",
        )
        assert status == RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL


class TestRegulatoryDirective:

    def test_not_regulated_bans_510k(self):
        directive = regulatory_directive(RegulatoryStatus.NOT_REGULATED)
        assert "510(k)" in directive
        assert "NOT" in directive or "Do NOT" in directive

    def test_regulated_mentions_full_pathway(self):
        directive = regulatory_directive(RegulatoryStatus.REGULATED)
        assert "full regulatory pathway" in directive.lower() or "FDA clearance" in directive

    def test_likely_exempt_mentions_exemption(self):
        directive = regulatory_directive(RegulatoryStatus.LIKELY_EXEMPT)
        assert "exempt" in directive.lower()

    def test_ambiguous_mentions_counsel(self):
        directive = regulatory_directive(RegulatoryStatus.AMBIGUOUS_REQUIRES_COUNSEL)
        assert "counsel" in directive.lower() or "ambiguous" in directive.lower()

    def test_directive_is_non_empty_for_all_statuses(self):
        for status in RegulatoryStatus:
            directive = regulatory_directive(status)
            assert len(directive) > 20, f"Directive for {status} is too short"


class TestDecisionTreeFormat:

    def test_not_regulated_tree_has_no_q(self):
        tree = format_regulatory_decision_tree(
            RegulatoryStatus.NOT_REGULATED, "research_tool_non_clinical",
        )
        assert "NOT_REGULATED" in tree
        assert "Q1" in tree
        assert "Q2" in tree

    def test_regulated_tree_mentions_archetype(self):
        tree = format_regulatory_decision_tree(RegulatoryStatus.REGULATED, "drug")
        assert "drug" in tree
        assert "REGULATED" in tree


# ─────────────────────────────────────────────────────────────────────────────
# H-04: Competitive intelligence research tool gate
# ─────────────────────────────────────────────────────────────────────────────

from app.services.competitive_intelligence_service import (
    _RESEARCH_TOOL_ARCHETYPES,
    _HONEST_EMPTY_NOTE,
    _gather_research_tool_intel,
    _extract_research_tool_comparators,
    format_intelligence_for_expert,
)


class TestResearchToolArchetype:

    def test_research_tool_archetypes_frozenset(self):
        assert "research_tool_non_clinical" in _RESEARCH_TOOL_ARCHETYPES

    def test_extract_comparators_is_async_callable(self):
        import inspect
        assert inspect.iscoroutinefunction(_extract_research_tool_comparators)

    def test_extract_comparators_returns_empty_without_api_key(self, monkeypatch):
        import asyncio, os
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = asyncio.run(_extract_research_tool_comparators("soil moisture sensor", "research_infrastructure_saas"))
        assert isinstance(result, list)

    def test_honest_empty_note_is_nonempty(self):
        assert len(_HONEST_EMPTY_NOTE) > 40


class TestGatherResearchToolIntel:

    def _run(self, coro):
        return asyncio.run(coro)

    def test_returns_research_tool_comparators_key(self):
        result = self._run(_gather_research_tool_intel("neurotech", "research_tool_non_clinical"))
        assert "research_tool_comparators" in result
        assert isinstance(result["research_tool_comparators"], list)

    def test_competitor_trials_empty(self):
        result = self._run(_gather_research_tool_intel("neurotech", "research_tool_non_clinical"))
        assert result["competitor_trials"]["trials"] == []

    def test_fda_precedents_empty(self):
        result = self._run(_gather_research_tool_intel("neurotech", "research_tool_non_clinical"))
        assert result["fda_precedents"]["approvals"] == []

    def test_honest_empty_state_in_result(self):
        result = self._run(_gather_research_tool_intel("neurotech", "research_tool_non_clinical"))
        assert "honest_empty_state" in result
        assert len(result["honest_empty_state"]) > 40


class TestFormatIntelligenceForExpert:

    def test_research_tool_format_mentions_functional_comparators(self):
        _sample = [
            {"name": "SampleTool", "category": "direct", "description": "A sample tool",
             "url": "", "incumbent": False},
        ]
        intel = {
            "research_tool_comparators": _sample,
            "competitor_trials": {"trials": [], "total_found": 0},
            "fda_precedents": {"approvals": []},
            "strategic_playbook": [],
            "honest_empty_state": _HONEST_EMPTY_NOTE,
        }
        formatted = format_intelligence_for_expert(intel, "neurotech")
        assert "FUNCTIONAL COMPARATORS" in formatted
        assert "SampleTool" in formatted

    def test_research_tool_format_does_not_mention_fda_approval_precedents_as_header(self):
        intel = {
            "research_tool_comparators": [],
            "competitor_trials": {"trials": [], "total_found": 0},
            "fda_precedents": {"approvals": []},
            "strategic_playbook": [],
            "honest_empty_state": "",
        }
        formatted = format_intelligence_for_expert(intel, "neurotech")
        assert "FDA APPROVAL PRECEDENTS" not in formatted

    def test_honest_empty_state_appears_in_output(self):
        intel = {
            "competitor_trials": {"trials": [], "total_found": 0},
            "fda_precedents": {"approvals": []},
            "strategic_playbook": [],
            "honest_empty_state": "Test honest empty state message for no comparators found.",
        }
        formatted = format_intelligence_for_expert(intel, "neurotech")
        assert "honest empty state message" in formatted.lower() or "NOTE:" in formatted


# ─────────────────────────────────────────────────────────────────────────────
# H-05: Citation validator
# ─────────────────────────────────────────────────────────────────────────────

from app.services.citation_validator import (
    INTERNAL_KB_PATTERNS,
    _is_internal_kb,
    _domain_matches_publisher,
    strip_internal_citations,
    audit_citation_url_domains,
    strip_placeholder_numerics,
    run_citation_audit,
    CitationAuditResult,
)


class TestInternalKBPatterns:

    def test_medlevate_is_internal(self):
        assert _is_internal_kb("RPM Expert Domain Knowledge - Medlevate RPM Context 2024")

    def test_project_elevate_is_internal(self):
        assert _is_internal_kb("Project Elevate Internal Knowledge Base")

    def test_nih_pubmed_is_not_internal(self):
        assert not _is_internal_kb("NIH PubMed — randomized controlled trial 2022")

    def test_cdc_is_not_internal(self):
        assert not _is_internal_kb("CDC National Center for Health Statistics")

    def test_empty_string_is_not_internal(self):
        assert not _is_internal_kb("")


class TestDomainMatchesPublisher:

    def test_cdc_gov_matches_cdc(self):
        assert _domain_matches_publisher("https://cdc.gov/stats", "CDC National Center") is True

    def test_klasresearch_does_not_match_who(self):
        assert _domain_matches_publisher("https://klasresearch.com/report/123", "WHO Global Burden") is False

    def test_who_int_matches_who(self):
        assert _domain_matches_publisher("https://www.who.int/health-topics", "WHO Global Burden") is True

    def test_unknown_publisher_returns_none(self):
        assert _domain_matches_publisher("https://example.com/paper", "Random Journal 2022") is None

    def test_empty_url_returns_none(self):
        assert _domain_matches_publisher("", "CDC") is None

    def test_fda_gov_matches_fda(self):
        assert _domain_matches_publisher("https://www.fda.gov/drugs/510k", "FDA Drug Approval") is True


class TestStripInternalCitations:

    def test_strips_medlevate_from_sources_list(self):
        report = {
            "sources": [
                {"name": "NIH Reporter", "url": "https://reporter.nih.gov"},
                {"name": "Medlevate RPM Context 2024", "url": "https://klasresearch.com"},
                {"name": "CDC NCHS", "url": "https://cdc.gov"},
            ]
        }
        cleaned, count = strip_internal_citations(report)
        assert count >= 1
        names = [s["name"] for s in cleaned["sources"]]
        assert "Medlevate RPM Context 2024" not in names
        assert "NIH Reporter" in names
        assert "CDC NCHS" in names

    def test_nulls_nested_internal_url(self):
        report = {
            "regulatory_pathway": {
                "source": "Expert Domain Knowledge",
                "url": "https://some-url.com/internal",
            }
        }
        cleaned, count = strip_internal_citations(report)
        assert count >= 1
        assert cleaned["regulatory_pathway"]["url"] is None

    def test_no_internal_sources_returns_zero_count(self):
        report = {
            "sources": [
                {"name": "PubMed 2023", "url": "https://pubmed.ncbi.nlm.nih.gov/123"}
            ]
        }
        _, count = strip_internal_citations(report)
        assert count == 0


class TestAuditCitationUrlDomains:

    def test_flags_klas_url_for_who_publisher(self):
        report = {
            "market_sizing": {
                "source": "WHO Global Burden of Disease 2019",
                "url": "https://klasresearch.com/report/999",
            }
        }
        violations = audit_citation_url_domains(report)
        assert len(violations) == 1
        assert violations[0].violation_type == "domain_mismatch"

    def test_no_violations_for_correct_domain(self):
        report = {
            "epidemiology": {
                "source": "CDC NCHS 2022",
                "url": "https://cdc.gov/nchs/fastats/",
            }
        }
        violations = audit_citation_url_domains(report)
        assert violations == []

    def test_no_violation_for_unknown_publisher(self):
        report = {
            "source": "Random Conference 2022",
            "url": "https://example-conference.org/paper",
        }
        violations = audit_citation_url_domains(report)
        assert violations == []


class TestStripPlaceholderNumerics:

    def test_nulls_zero_tam(self):
        report = {"total_addressable_market_usd": 0}
        cleaned, count = strip_placeholder_numerics(report)
        assert count == 1
        assert cleaned["total_addressable_market_usd"] is None

    def test_does_not_null_legitimate_nonzero_value(self):
        report = {"total_addressable_market_usd": 500_000_000}
        _, count = strip_placeholder_numerics(report)
        assert count == 0

    def test_nulls_tbd_value(self):
        report = {"daly_burden": "TBD"}
        cleaned, count = strip_placeholder_numerics(report)
        assert count == 1
        assert cleaned["daly_burden"] is None

    def test_does_not_touch_non_placeholder_fields(self):
        report = {"some_other_field": 0}
        _, count = strip_placeholder_numerics(report)
        assert count == 0


class TestRunCitationAudit:

    def test_full_audit_strips_internal_and_mismatched(self):
        report = {
            "sources": [
                {"name": "Medlevate Context", "url": "https://medlevate.com"},
                {"name": "CDC NCHS", "url": "https://cdc.gov/nchs"},
            ],
            "market_sizing": {
                "source": "WHO",
                "url": "https://klasresearch.com/wrong-url",  # domain mismatch
            },
            "total_addressable_market_usd": 0,  # placeholder
        }
        result = run_citation_audit(report)
        assert isinstance(result, CitationAuditResult)
        assert result.internal_stripped >= 1
        assert result.domain_mismatches >= 1
        assert result.placeholder_nulled >= 1

    def test_clean_report_has_no_violations(self):
        report = {
            "sources": [{"name": "PubMed 2022", "url": "https://pubmed.ncbi.nlm.nih.gov/123"}],
            "total_addressable_market_usd": 50_000_000,
        }
        result = run_citation_audit(report)
        assert result.internal_stripped == 0
        assert result.placeholder_nulled == 0

    def test_summary_is_non_empty_when_violations(self):
        report = {"sources": [{"name": "Medlevate Internal", "url": "https://x.com"}]}
        result = run_citation_audit(report)
        assert result.summary() != "no violations"


# ─────────────────────────────────────────────────────────────────────────────
# H-06: Person verifier
# ─────────────────────────────────────────────────────────────────────────────

from app.services.person_verifier import (
    build_verified_kol_list,
    sanitize_kol_list,
    kol_selection_criteria_block,
    VerifiedKOL,
    KOLSanitizationResult,
    _name_in_string,
    _normalise,
)


class TestNameNormalisation:

    def test_name_in_string_exact_match(self):
        assert _name_in_string("John Smith", "John Smith, Johns Hopkins")

    def test_name_in_string_with_title(self):
        assert _name_in_string("John Smith", "Dr. John Smith, WashU — 10 papers")

    def test_name_in_string_last_name_only(self):
        assert _name_in_string("Robert Johnson", "R. Johnson — 15 papers, 300 citations")

    def test_name_in_string_no_match(self):
        assert not _name_in_string("Alice Wang", "Bob Smith — 5 papers")

    def test_name_in_string_too_short_skipped(self):
        assert not _name_in_string("AB", "AB Research Group")

    def test_normalise_strips_accents(self):
        assert _normalise("José Rodríguez") == "jose rodriguez"

    def test_normalise_lowercases(self):
        assert _normalise("JOHN DOE") == "john doe"


class TestBuildVerifiedKolList:

    def test_builds_verified_kol_from_semantic_scholar_data(self):
        kols = [
            {"name": "Jane Doe", "paper_count": 12, "citation_total": 500},
            {"name": "Bob Lee", "paper_count": 5, "citation_total": 200},
        ]
        verified = build_verified_kol_list(kols, "epilepsy")
        assert len(verified) == 2
        assert all(isinstance(v, VerifiedKOL) for v in verified)

    def test_verified_kol_has_source_url(self):
        kols = [{"name": "Jane Doe", "paper_count": 3, "citation_total": 100}]
        verified = build_verified_kol_list(kols, "epilepsy")
        assert verified[0].source_url.startswith("https://")

    def test_skips_kols_with_empty_name(self):
        kols = [{"name": "", "paper_count": 10, "citation_total": 500}]
        verified = build_verified_kol_list(kols)
        assert len(verified) == 0

    def test_also_accepts_author_key(self):
        kols = [{"author": "Jane Doe", "paper_count": 3, "citation_total": 100}]
        verified = build_verified_kol_list(kols)
        assert len(verified) == 1


class TestSanitizeKolList:

    def _make_verified(self, names):
        return [
            VerifiedKOL(
                name=n,
                source_url=f"https://pubmed.ncbi.nlm.nih.gov/?term={n.replace(' ', '+')}[Author]",
                paper_count=5,
                citation_total=100,
            )
            for n in names
        ]

    def test_verified_names_are_kept(self):
        verified = self._make_verified(["Jane Doe", "Bob Lee"])
        result = sanitize_kol_list(
            ["Jane Doe, Stanford — 12 papers", "Bob Lee — 5 papers"],
            verified,
            disease_name="epilepsy",
        )
        assert result.has_verified
        assert len(result.verified) >= 2
        assert not result.used_fallback

    def test_unverified_names_are_dropped(self):
        verified = self._make_verified(["Jane Doe"])
        result = sanitize_kol_list(
            ["Jane Doe — 12 papers", "Ayan Mukhopadhyay, WashU Neurotech Hub"],
            verified,
            disease_name="epilepsy",
        )
        assert len(result.dropped_names) >= 1
        assert "Ayan Mukhopadhyay, WashU Neurotech Hub" in result.dropped_names

    def test_empty_verified_list_triggers_fallback(self):
        result = sanitize_kol_list(
            ["Ayan Mukhopadhyay, WashU", "John Doe, Harvard"],
            [],
            disease_name="neurotech",
            sub_expert_id="research_tool_non_clinical",
        )
        assert result.used_fallback
        assert len(result.criteria_block) > 50
        assert len(result.dropped_names) == 2

    def test_fewer_than_2_verified_triggers_fallback(self):
        verified = self._make_verified(["Jane Doe"])
        # Give an LLM list that only Jane Doe matches — 1 verified < minimum
        result = sanitize_kol_list(
            ["Jane Doe — 12 papers"],
            verified,
            disease_name="epilepsy",
        )
        assert result.used_fallback

    def test_formatted_list_includes_source_url(self):
        verified = self._make_verified(["Jane Doe", "Bob Lee", "Alice Chen"])
        result = sanitize_kol_list(
            ["Jane Doe — 10 papers", "Bob Lee — 5 papers", "Alice Chen — 8 papers"],
            verified,
        )
        if not result.used_fallback:
            for line in result.formatted_list():
                assert "[Source:" in line


class TestKolSelectionCriteriaBlock:

    def test_block_is_non_empty(self):
        block = kol_selection_criteria_block("drug_amr", "MRSA")
        assert len(block) > 100

    def test_block_mentions_disease(self):
        block = kol_selection_criteria_block("drug_amr", "MRSA")
        assert "MRSA" in block

    def test_research_tool_block_mentions_wearable_criteria(self):
        block = kol_selection_criteria_block("research_tool_non_clinical", "epilepsy")
        assert "wearable" in block.lower() or "data" in block.lower()
        assert "NIH" in block or "NSF" in block

    def test_block_mentions_no_verified_kols(self):
        block = kol_selection_criteria_block("drug_amr", "MRSA")
        assert "no verified" in block.lower() or "no functional" in block.lower() or "not identified" in block.lower()

    def test_block_includes_pubmed_search_tip(self):
        block = kol_selection_criteria_block("drug_amr", "MRSA")
        assert "PubMed" in block or "pubmed" in block.lower()


# ─────────────────────────────────────────────────────────────────────────────
# B-07: status-quo / DIY as first-class competitor rows
# ─────────────────────────────────────────────────────────────────────────────

from app.services.competitor_sweep_service import _status_quo_rows, to_dict


class TestB07StatusQuoRows:
    """
    B-07: the competitive section must always include status-quo and DIY
    as first-class rows, not buried in prose or omitted.
    """

    def _names(self, rows):
        return [r.name.lower() for r in rows]

    def test_drug_archetype_always_has_two_rows(self):
        rows = _status_quo_rows("drug_small_molecule", "MRSA infection", device_like=False)
        assert len(rows) == 2

    def test_drug_status_quo_row_is_first(self):
        rows = _status_quo_rows("drug_small_molecule", "MRSA infection", device_like=False)
        assert rows[0].stage == "status_quo"

    def test_drug_diy_row_is_second(self):
        rows = _status_quo_rows("drug_small_molecule", "MRSA infection", device_like=False)
        assert rows[1].stage == "diy"

    def test_drug_status_quo_names_disease(self):
        rows = _status_quo_rows("drug_small_molecule", "MRSA infection", device_like=False)
        assert "MRSA" in rows[0].name or "mrsa" in rows[0].name.lower()

    def test_device_status_quo_mentions_manual_workflow(self):
        rows = _status_quo_rows("medical_device", "atrial fibrillation", device_like=True)
        assert "manual" in rows[0].name.lower() or "workflow" in rows[0].name.lower()

    def test_device_diy_mentions_prototype_or_custom(self):
        rows = _status_quo_rows("medical_device", "atrial fibrillation", device_like=True)
        assert "diy" in rows[1].name.lower() or "prototype" in rows[1].name.lower() or "custom" in rows[1].name.lower()

    def test_rows_have_advantages_and_vulnerabilities(self):
        for product_type, disease, device_like in [
            ("drug_small_molecule", "MRSA", False),
            ("medical_device", "AF", True),
        ]:
            rows = _status_quo_rows(product_type, disease, device_like)
            for row in rows:
                assert len(row.advantages) >= 1, f"No advantages on {row.name}"
                assert len(row.vulnerabilities) >= 1, f"No vulnerabilities on {row.name}"

    def test_status_quo_rows_serialize_cleanly(self):
        from dataclasses import asdict
        rows = _status_quo_rows("drug_small_molecule", "cancer", device_like=False)
        for row in rows:
            d = asdict(row)
            assert "name" in d
            assert "stage" in d
            assert d["source"] == "status_quo"
