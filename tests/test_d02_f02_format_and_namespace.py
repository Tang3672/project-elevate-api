"""
D-02 + F-02 — PMC/PMID namespace normalization and USD formatting fixes.

D-02: PMC IDs (PMC\d+) are NOT PubMed IDs. Also covers sentinel "PMID N/A" entries
      rendered as papers. Both now treated as null-PMID → stricter gate applies.

F-02: licensing_upfront_range must not render $50K as "$0.05M".
      _normalize_usd_range post-processes Haiku's output to convert $0.XXM → $XXK.
"""

from __future__ import annotations

import pytest

from app.services.pubmed_service import filter_literature_citations

# ── helpers ───────────────────────────────────────────────────────────────────

WEARABLE_IDEA = "Hublink: a non-clinical wearable data platform for academic PIs."
RT_EXPERT     = "research_tool_non_clinical"


def _cit(title: str, pmid: str = "99999999999") -> dict:
    return {
        "pmid":      pmid,
        "title":     title,
        "authors":   "Smith J et al.",
        "journal":   "J Test",
        "year":      2024,
        "relevance": "Relevant to platform adoption in academic research settings.",
    }


# ── D-02: PMC ID namespace ────────────────────────────────────────────────────

class TestPmcNamespaceNormalization:

    def test_pmc_id_is_treated_as_null_pmid_path(self):
        """PMC12648116 is a PMC ID, not a PMID. Must not bypass the strict gate."""
        # Laryngeal mask airways paper — completely off-domain for a wearable platform.
        # With a real numeric PMID it would pass through (threshold=0 for PMID-backed).
        # With the PMC namespace fix it goes through the null-PMID path → strict gate.
        cits = [_cit(
            "Eliminating protein from reusable laryngeal mask airways",
            pmid="PMC12648116",
        )]
        result = filter_literature_citations(cits, WEARABLE_IDEA, RT_EXPERT)
        # Either dropped by strict gate (null-PMID → OpenAlex/Crossref can't verify
        # a laryngeal mask paper as relevant to a wearable PI data platform) or
        # the gate catches zero overlap. We assert it doesn't silently pass through.
        # The important invariant: off-domain papers via PMC IDs must not survive.
        assert result == [], (
            "PMC12648116 (laryngeal mask airways) must not pass for a wearable data platform. "
            "PMC IDs are now normalised to null-PMID, applying the strict verification gate."
        )

    def test_numeric_pmid_still_processed_normally(self):
        """A real numeric PMID path must still work (not accidentally broken)."""
        # Use a non-existent PMID so resolve_pmid() returns None (no network needed).
        # Non-existent PMID → passes as before (unresolvable → threshold=0).
        cits = [_cit("REDCap: a metadata-driven methodology for research informatics", pmid="88888888888")]
        result = filter_literature_citations(cits, WEARABLE_IDEA, RT_EXPERT)
        assert isinstance(result, list), "Must return a list"

    def test_pmid_na_sentinel_is_dropped(self):
        """'PMID N/A' with a no-results sentinel title must be dropped."""
        cits = [{
            "pmid":      "N/A",
            "title":     "No PubMed publications indexed for 'Hublink'",
            "authors":   "",
            "year":      2024,
            "relevance": "Demonstrates that soil moisture data has measurable epidemiological signal value.",
        }]
        result = filter_literature_citations(cits, WEARABLE_IDEA, RT_EXPERT)
        assert result == [], (
            "PMID 'N/A' with sentinel title 'No PubMed publications indexed' must be dropped. "
            "It is a plumbing artifact, not a citable paper."
        )

    def test_na_string_pmid_treated_as_null(self):
        """Non-numeric PMIDs like 'NA', 'None', '' must fall through to null-PMID gate."""
        for sentinel_pmid in ("NA", "None", "null", "n/a"):
            cits = [_cit(
                "Eliminating protein from reusable laryngeal mask airways",
                pmid=sentinel_pmid,
            )]
            result = filter_literature_citations(cits, WEARABLE_IDEA, RT_EXPERT)
            assert result == [], (
                f"Sentinel PMID '{sentinel_pmid}' with off-domain title must be dropped "
                f"(treated as null-PMID → strict gate)"
            )

    def test_pmc_id_with_on_domain_title_passes_if_verified(self):
        """PMC ID + on-domain title: strict gate allows it if OpenAlex/Crossref resolves it."""
        # This test verifies the happy path doesn't break — if the title is on-domain
        # and resolvable, the paper should pass. We can't mock the network easily,
        # so just check the gate doesn't crash on PMC IDs.
        cits = [_cit("REDCap wearable sensor data management for academic research labs", pmid="PMC00000001")]
        # Whether it passes or fails depends on network; just assert no exception.
        result = filter_literature_citations(cits, WEARABLE_IDEA, RT_EXPERT)
        assert isinstance(result, list)


# ── D-02: sentinel title prefixes ────────────────────────────────────────────

class TestSentinelTitleDrop:

    @pytest.mark.parametrize("sentinel_title", [
        "No PubMed publications indexed for 'Hublink'",
        "No PubMed publications found",
        "No publications indexed",
        "No results found",
        "Not indexed in PubMed",
        "No papers found for this query",
    ])
    def test_sentinel_title_dropped(self, sentinel_title: str):
        """Titles that are no-results sentinels must be dropped as non-papers."""
        cits = [{"pmid": "N/A", "title": sentinel_title, "authors": "", "year": 2024}]
        result = filter_literature_citations(cits, WEARABLE_IDEA, RT_EXPERT)
        assert result == [], f"Sentinel title '{sentinel_title[:40]}…' must be dropped"


# ── F-02: _normalize_usd_range ────────────────────────────────────────────────

class TestNormalizeUsdRange:

    @pytest.fixture(autouse=True)
    def _import(self):
        from app.services.expert_panel import _normalize_usd_range
        self.norm = _normalize_usd_range

    def test_sub_million_decimal_m_converted_to_k(self):
        assert self.norm("$0.05M–$0.15M") == "$50K–$150K"

    def test_half_million_decimal_converted(self):
        assert self.norm("$0.5M–$2M") == "$500K–$2M"

    def test_whole_millions_unchanged(self):
        assert self.norm("$5M–$30M") == "$5M–$30M"

    def test_already_in_k_format_unchanged(self):
        assert self.norm("$50K–$150K") == "$50K–$150K"

    def test_empty_string_unchanged(self):
        assert self.norm("") == ""

    def test_none_like_string_unchanged(self):
        assert self.norm("—") == "—"

    def test_large_deal_unchanged(self):
        assert self.norm("$100M–$500M") == "$100M–$500M"

    def test_mixed_range_converts_only_sub_million(self):
        """$0.1M–$5M → $100K–$5M (only the sub-1M value changes)."""
        assert self.norm("$0.1M–$5M") == "$100K–$5M"
