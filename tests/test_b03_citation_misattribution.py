"""
B-03 — Citation misattribution / source-claim binding
=======================================================
Catches two failure modes without an LLM call:

  1. Source-type mismatch: a source is cited for a claim it cannot support
     (Rock Health for market size, AUTM for TAM, CMS MPFS for CAGR).
  2. Price-segment mismatch: a research_tool product shows enterprise-SaaS
     pricing for academic PI buyers ($75k+ annual).

Deterministic checks live in app/services/source_type_guard.py and are
called inside source_verifier_node before the LLM pass.

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import inspect

import pytest

from app.services.source_type_guard import (
    check_price_segment_consistency,
    check_source_type_bindings,
    _min_usd_from_str,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _item(source: str, claim: str, field: str = "market_sizing.steps") -> dict:
    return {"field": field, "source": source, "claim": claim, "url": ""}


def _first_flag(source: str, claim: str, **kw) -> dict | None:
    flags = check_source_type_bindings([_item(source, claim, **kw)])
    return flags[0] if flags else None


# ══════════════════════════════════════════════════════════════════════════════
# Rock Health rules
# ══════════════════════════════════════════════════════════════════════════════

class TestRockHealthRules:

    def test_flagged_for_tam(self):
        f = _first_flag("Rock Health Digital Health Funding 2023",
                         "US hospital TAM: 2500000000 USD")
        assert f is not None, "Rock Health cited for TAM must be flagged"

    def test_flagged_for_market_size(self):
        f = _first_flag("Rock Health Report 2022",
                         "digital health market size: 45 billion")
        assert f is not None

    def test_flagged_for_revenue(self):
        f = _first_flag("Rock Health",
                         "total revenue projection: 500000000 USD")
        assert f is not None

    def test_flagged_for_pricing(self):
        f = _first_flag("Rock Health 2023",
                         "pricing per user: 75000 USD/yr")
        assert f is not None

    def test_flagged_for_sales(self):
        f = _first_flag("Rock Health Digital Health",
                         "first-year sales: 12000000 USD")
        assert f is not None

    def test_flagged_for_addressable(self):
        f = _first_flag("Rock Health",
                         "total addressable opportunity: 3.2B")
        assert f is not None

    def test_clean_for_vc_funding(self):
        """Rock Health is a valid source for VC investment data."""
        flags = check_source_type_bindings([_item(
            "Rock Health Digital Health Funding Report 2023",
            "VC investment into digital health: 14.7B in 2023",
        )])
        assert flags == [], (
            "Rock Health cited for VC investment tracking must NOT be flagged"
        )

    def test_clean_for_deal_count(self):
        flags = check_source_type_bindings([_item(
            "Rock Health",
            "number of digital health deals: 572 in 2022",
        )])
        assert flags == []


# ══════════════════════════════════════════════════════════════════════════════
# AUTM rules
# ══════════════════════════════════════════════════════════════════════════════

class TestAUTMRules:

    def test_flagged_for_tam(self):
        f = _first_flag("AUTM Licensing Activity Survey 2022",
                         "total addressable market: 8.5B USD")
        assert f is not None

    def test_flagged_for_market(self):
        f = _first_flag("AUTM 2022",
                         "US market for wearable research tools: 1.2B")
        assert f is not None

    def test_flagged_for_addressable(self):
        f = _first_flag("AUTM",
                         "addressable market opportunity: 3.4B")
        assert f is not None

    def test_clean_for_licensing_deals(self):
        """AUTM is appropriate for licensing deal counts."""
        flags = check_source_type_bindings([_item(
            "AUTM Licensing Activity Survey 2022",
            "number of executed licenses: 5,908 university deals",
        )])
        assert flags == []

    def test_clean_for_royalty_rates(self):
        flags = check_source_type_bindings([_item(
            "AUTM",
            "median royalty rate: 3.5% for life sciences",
        )])
        assert flags == []


# ══════════════════════════════════════════════════════════════════════════════
# CMS MPFS rules
# ══════════════════════════════════════════════════════════════════════════════

class TestCMSMPFSRules:

    def test_flagged_for_cagr(self):
        f = _first_flag("CMS MPFS Proposed Rule 2024",
                         "antibiotic market CAGR: 8.3% through 2029")
        assert f is not None

    def test_flagged_for_growth(self):
        f = _first_flag("CMS MPFS 2023",
                         "market growth rate: 6.2% annually")
        assert f is not None

    def test_flagged_for_trend(self):
        f = _first_flag("CMS Physician Fee Schedule",
                         "market trend: 5% annual increase in demand")
        assert f is not None

    def test_physician_fee_schedule_alias_matched(self):
        f = _first_flag("Medicare Physician Fee Schedule Lookup Tool",
                         "hospital market CAGR: 7%")
        assert f is not None, "Partial match on 'physician fee schedule' must flag"

    def test_clean_for_reimbursement_rate(self):
        """CMS MPFS is valid for reimbursement rate lookups."""
        flags = check_source_type_bindings([_item(
            "CMS MPFS 2024 Proposed Rule",
            "CPT 87641 reimbursement rate: $85.40",
        )])
        assert flags == []

    def test_clean_for_medicare_payment(self):
        flags = check_source_type_bindings([_item(
            "CMS MPFS",
            "Medicare payment for rapid PCR: $142 per test",
        )])
        assert flags == []


# ══════════════════════════════════════════════════════════════════════════════
# Clean sources — must never be flagged
# ══════════════════════════════════════════════════════════════════════════════

class TestCleanSourcesNotFlagged:

    def test_cdc_market_sizing_clean(self):
        flags = check_source_type_bindings([_item(
            "CDC AR Threats Report 2019",
            "MRSA addressable patient population: 119247 infections/yr",
        )])
        assert flags == []

    def test_marketsandmarkets_tam_clean(self):
        flags = check_source_type_bindings([_item(
            "MarketsandMarkets AMR Diagnostics Report 2023",
            "US hospital TAM: 1.2B USD by 2028",
        )])
        assert flags == []

    def test_iqvia_revenue_clean(self):
        flags = check_source_type_bindings([_item(
            "IQVIA Institute Drug Expenditure Report 2023",
            "total US market revenue for IV antibiotics: 8.7B",
        )])
        assert flags == []

    def test_fda_clean(self):
        flags = check_source_type_bindings([_item(
            "FDA Guidance QIDP 2012",
            "LPAD pathway approval timeline: 6 months priority review",
        )])
        assert flags == []

    def test_empty_sources_list(self):
        assert check_source_type_bindings([]) == []


# ══════════════════════════════════════════════════════════════════════════════
# Flag format
# ══════════════════════════════════════════════════════════════════════════════

class TestFlagFormat:

    def _flag(self) -> dict:
        return _first_flag("Rock Health 2023", "US hospital TAM: 2.5B")

    def test_flag_severity_is_warning(self):
        assert self._flag()["severity"] == "WARNING"

    def test_flag_severity_is_not_error(self):
        assert self._flag()["severity"] != "ERROR"

    def test_flag_has_category_source(self):
        assert self._flag()["category"] == "SOURCE"

    def test_flag_has_field_from_input(self):
        f = _first_flag("Rock Health 2023", "US hospital TAM: 2.5B",
                         field="market_sizing.steps")
        assert f["field"] == "market_sizing.steps"

    def test_flag_has_issue_string(self):
        f = self._flag()
        assert isinstance(f["issue"], str) and len(f["issue"]) > 10

    def test_flag_has_suggestion_string(self):
        f = self._flag()
        assert isinstance(f["suggestion"], str) and len(f["suggestion"]) > 10

    def test_flag_issue_names_the_source(self):
        f = _first_flag("Rock Health Digital Health Report",
                         "US market size: 4.5B")
        assert "Rock Health" in f["issue"]

    def test_flag_issue_names_the_keyword(self):
        f = _first_flag("AUTM Licensing Survey 2022",
                         "total addressable market: 8.5B")
        assert any(kw in f["issue"].lower() for kw in ("addressable", "market", "tam"))


# ══════════════════════════════════════════════════════════════════════════════
# Edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestEdgeCases:

    def test_none_source_no_crash(self):
        flags = check_source_type_bindings([{"source": None, "claim": "US hospital TAM: 2.5B"}])
        assert isinstance(flags, list)

    def test_empty_source_string_no_crash(self):
        flags = check_source_type_bindings([{"source": "", "claim": "US hospital TAM: 2.5B"}])
        assert flags == []

    def test_none_claim_no_crash(self):
        flags = check_source_type_bindings([{"source": "Rock Health", "claim": None}])
        assert isinstance(flags, list)

    def test_case_insensitive_source_match(self):
        f = _first_flag("ROCK HEALTH DIGITAL HEALTH 2023", "US hospital market size: 3B")
        assert f is not None, "Source matching must be case-insensitive"

    def test_source_with_year_suffix_matched(self):
        f = _first_flag("Rock Health Digital Health Funding Report 2024",
                         "addressable market: 5B USD")
        assert f is not None

    def test_multiple_sources_each_flagged_independently(self):
        sources = [
            _item("Rock Health", "US TAM: 2.5B"),
            _item("AUTM 2022", "total addressable market: 8.5B"),
        ]
        flags = check_source_type_bindings(sources)
        assert len(flags) == 2

    def test_one_flag_per_item_per_rule(self):
        """Even if multiple keywords match, only one flag per (item, rule) is emitted."""
        f = _first_flag("Rock Health", "US TAM market size revenue: 3B")
        assert f is not None
        flags = check_source_type_bindings([_item("Rock Health", "US TAM market size revenue: 3B")])
        rock_flags = [fl for fl in flags if "Rock Health" in (fl.get("issue") or "")]
        assert len(rock_flags) == 1, "Should emit at most 1 flag per (item, rule)"

    def test_unknown_source_no_flag(self):
        flags = check_source_type_bindings([_item(
            "Proprietary Transcriptomic Atlas 2024",
            "US hospital TAM: 2.5B USD",
        )])
        assert flags == []

    def test_field_defaults_to_sources_when_missing(self):
        flags = check_source_type_bindings([{"source": "Rock Health", "claim": "market size"}])
        assert flags[0]["field"] == "sources"


# ══════════════════════════════════════════════════════════════════════════════
# Price string parser
# ══════════════════════════════════════════════════════════════════════════════

class TestMinUsdFromStr:

    def test_range_str(self):
        assert _min_usd_from_str("$50,000-200,000") == 50_000.0

    def test_k_shorthand_lower(self):
        assert _min_usd_from_str("$5k-$15k/yr") == 5_000.0

    def test_single_value(self):
        assert _min_usd_from_str("$75,000") == 75_000.0

    def test_per_course(self):
        # 800 is filtered (< 1000 floor); 1500 is the only remaining value
        assert _min_usd_from_str("$800-1,500/course") == 1_500.0

    def test_empty_string(self):
        assert _min_usd_from_str("") == 0.0

    def test_no_numbers(self):
        assert _min_usd_from_str("contact for pricing") == 0.0

    def test_k_shorthand_upper(self):
        assert _min_usd_from_str("$75K-$200K") == 75_000.0


# ══════════════════════════════════════════════════════════════════════════════
# Price-segment consistency
# ══════════════════════════════════════════════════════════════════════════════

def _seg(name: str, annual_spend: str) -> dict:
    return {"segment_name": name, "annual_spend_per_facility": annual_spend,
            "price_per_unit": "", "buyer_count": "100", "decision_maker": "PI"}


class TestPriceSegmentConsistency:

    def test_enterprise_price_flagged_for_research_tool(self):
        segs = [_seg("Academic PI Labs", "$75,000-200,000")]
        flags = check_price_segment_consistency(segs, "research_tool")
        assert len(flags) == 1

    def test_normal_price_clean_for_research_tool(self):
        segs = [_seg("Academic PI Labs", "$5,000-15,000")]
        flags = check_price_segment_consistency(segs, "research_tool")
        assert flags == []

    def test_drug_product_type_not_checked(self):
        """Price check only applies to research_tool."""
        segs = [_seg("Hospital Formulary", "$75,000-200,000")]
        flags = check_price_segment_consistency(segs, "drug")
        assert flags == []

    def test_unknown_product_type_no_flag(self):
        segs = [_seg("Enterprise Accounts", "$75,000-200,000")]
        flags = check_price_segment_consistency(segs, "unknown_type")
        assert flags == []

    def test_75k_minimum_flagged(self):
        segs = [_seg("University Core Labs", "$75,000")]
        flags = check_price_segment_consistency(segs, "research_tool")
        assert len(flags) == 1

    def test_50k_boundary_not_flagged(self):
        """50k exactly is the threshold — not flagged."""
        segs = [_seg("Hospital Lab", "$50,000")]
        flags = check_price_segment_consistency(segs, "research_tool")
        assert flags == []

    def test_price_via_k_shorthand_flagged(self):
        segs = [_seg("Biotech Labs", "$75k-$150k/yr")]
        flags = check_price_segment_consistency(segs, "research_tool")
        assert len(flags) == 1

    def test_empty_buyer_segments_clean(self):
        flags = check_price_segment_consistency([], "research_tool")
        assert flags == []

    def test_segment_missing_price_fields_no_crash(self):
        segs = [{"segment_name": "Unknown", "buyer_count": "50"}]
        flags = check_price_segment_consistency(segs, "research_tool")
        assert flags == []

    def test_flag_format(self):
        segs = [_seg("Academic PI Labs", "$75,000-200,000")]
        f = check_price_segment_consistency(segs, "research_tool")[0]
        assert f["severity"] == "WARNING"
        assert f["category"] == "SOURCE"
        assert f["field"] == "market_access.buyer_segments"
        assert "75,000" in f["issue"] or "75000" in f["issue"]


# ══════════════════════════════════════════════════════════════════════════════
# Integration: guard is wired into source_verifier_node
# ══════════════════════════════════════════════════════════════════════════════

class TestGuardWiredIntoValidationGraph:

    def test_source_type_guard_imported_in_node(self):
        import app.services.validation_graph as vg
        src = inspect.getsource(vg.source_verifier_node)
        assert "check_source_type_bindings" in src, (
            "source_verifier_node must call check_source_type_bindings"
        )

    def test_price_segment_check_in_node(self):
        import app.services.validation_graph as vg
        src = inspect.getsource(vg.source_verifier_node)
        assert "check_price_segment_consistency" in src, (
            "source_verifier_node must call check_price_segment_consistency"
        )

    def test_deterministic_flags_merged_before_llm(self):
        """Deterministic flags must be combined with LLM flags, not replace them."""
        import app.services.validation_graph as vg
        src = inspect.getsource(vg.source_verifier_node)
        assert "deterministic_flags" in src
        assert "llm_flags" in src or "deterministic_flags +" in src

    def test_source_type_guard_module_importable(self):
        from app.services.source_type_guard import (  # noqa: F401
            check_source_type_bindings,
            check_price_segment_consistency,
        )

    def test_guard_rules_cover_rock_health(self):
        from app.services.source_type_guard import _SOURCE_TYPE_RULES
        names = [r["name"] for r in _SOURCE_TYPE_RULES]
        assert "rock_health" in names

    def test_guard_rules_cover_autm(self):
        from app.services.source_type_guard import _SOURCE_TYPE_RULES
        names = [r["name"] for r in _SOURCE_TYPE_RULES]
        assert "autm" in names

    def test_guard_rules_cover_cms_mpfs(self):
        from app.services.source_type_guard import _SOURCE_TYPE_RULES
        names = [r["name"] for r in _SOURCE_TYPE_RULES]
        assert "cms_mpfs" in names
