"""G.2 + G.3 — Cross-run contamination guard and literature relevance gate.

G.2: _sanitize_product_name() blocks stale product_name from prior runs.
G.3: filter_literature_citations() now:
  - Drops null-PMID citations that can't be verified via OpenAlex or Crossref
  - Drops citations scoring below the relevance threshold (score < 6)
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ── G.2: product_name sanitizer ───────────────────────────────────────────────

class TestSanitizeProductName:
    """Tests for the server-side cross-run contamination guard."""

    def _get(self):
        from app.api.alignment import _sanitize_product_name
        return _sanitize_product_name

    def test_matching_name_passes_through(self):
        fn = self._get()
        result = fn("Hublink", "Hublink is a cloud sync platform for neuroscience labs")
        assert result == "Hublink"

    def test_partial_word_match_passes_through(self):
        fn = self._get()
        # "NeuroSync" → "neuro" partial; "sync" is 4 chars so it's significant
        # idea contains "sync" and "neuro" → should pass
        result = fn("NeuroSync", "a neuroscience lab data sync device for wearables")
        assert result == "NeuroSync"

    def test_stale_name_from_prior_run_is_cleared(self):
        fn = self._get()
        # "Hublink" was the prior product; the new idea is about soil sensors
        result = fn("Hublink", "soil moisture sensor for precision agriculture field trials")
        assert result is None, (
            f"Expected None for stale product_name 'Hublink', got {result!r}"
        )

    def test_none_passes_through_unchanged(self):
        fn = self._get()
        assert fn(None, "any idea text at all") is None

    def test_empty_string_passes_through(self):
        fn = self._get()
        assert fn("", "any idea text at all") == ""

    def test_very_short_name_passes_through(self):
        fn = self._get()
        # Name with no words ≥4 chars → can't validate → pass through
        assert fn("BIO", "bioinformatics tool") == "BIO"

    def test_case_insensitive_match(self):
        fn = self._get()
        result = fn("MEDLEVATE", "medlevate is a market sizing platform for PIs")
        assert result == "MEDLEVATE"

    def test_multi_word_name_partial_match_passes(self):
        fn = self._get()
        # "SoilSense Pro" — "soil" and "sense" appear in idea → should pass
        result = fn("SoilSense Pro", "soil sensor device for field sensing in agriculture")
        assert result == "SoilSense Pro"


# ── G.3: null-PMID citations dropped when not verifiable ─────────────────────

class TestNullPmidVerification:
    """Null-PMID citations must be verified via OpenAlex or Crossref or dropped."""

    def _filter(self, citations, idea="soil moisture sensor for USDA field trials"):
        from app.services.pubmed_service import filter_literature_citations
        return filter_literature_citations(citations, idea, sub_expert_id="research_tool_non_clinical")

    def test_null_pmid_verified_via_openalex_is_kept(self):
        fake_meta = {
            "title":        "Soil Moisture Monitoring in Precision Agriculture",
            "authors":      "Smith et al.",
            "journal":      "Agricultural Water Management",
            "year":         "2022",
            "doi":          "10.1234/agri.2022.001",
            "url":          "https://doi.org/10.1234/agri.2022.001",
            "verified_via": "openAlex",
        }
        citation = {
            "pmid": "",
            "title": "Soil Moisture Monitoring in Precision Agriculture",
            "authors": "Smith et al.",
            "journal": "Agri Water Mgmt",
            "year": "2022",
            "relevance": "Covers soil sensor deployment in field trials.",
        }
        with patch("app.services.pubmed_service.resolve_via_openalex", return_value=fake_meta):
            result = self._filter([citation])
        assert len(result) == 1, f"Expected citation to pass; got {result}"
        assert result[0].get("verified_via") == "openAlex"

    def test_null_pmid_falls_back_to_crossref(self):
        fake_meta = {
            "title":        "Soil Moisture Monitoring in Precision Agriculture",
            "authors":      "Smith et al.",
            "journal":      "Agricultural Water Management",
            "year":         "2022",
            "doi":          "10.5678/cr.2022",
            "url":          "https://doi.org/10.5678/cr.2022",
            "verified_via": "crossref",
        }
        citation = {
            "pmid": "",
            "title": "Soil Moisture Monitoring in Precision Agriculture",
            "relevance": "Documents field sensor adoption.",
        }
        with patch("app.services.pubmed_service.resolve_via_openalex", return_value=None), \
             patch("app.services.pubmed_service.resolve_via_crossref", return_value=fake_meta):
            result = self._filter([citation])
        assert len(result) == 1
        assert result[0].get("verified_via") == "crossref"

    def test_null_pmid_not_found_anywhere_is_dropped(self):
        """A citation with null PMID that can't be verified anywhere is dropped."""
        citation = {
            "pmid": "",
            "title": "Invented Paper About Soil Sensing That Doesn't Exist",
            "relevance": "Would be great if it existed.",
        }
        with patch("app.services.pubmed_service.resolve_via_openalex", return_value=None), \
             patch("app.services.pubmed_service.resolve_via_crossref", return_value=None):
            result = self._filter([citation])
        assert result == [], f"Unverifiable null-PMID citation must be dropped; got {result}"

    def test_null_pmid_with_no_title_is_dropped(self):
        citation = {"pmid": "", "title": "", "relevance": "something"}
        with patch("app.services.pubmed_service.resolve_via_openalex", return_value=None):
            result = self._filter([citation])
        assert result == []


# ── G.3: relevance gate ───────────────────────────────────────────────────────

class TestRelevanceGate:
    """_keyword_relevance_score and the gate wired into filter_literature_citations."""

    def test_score_on_topic_paper_above_threshold(self):
        from app.services.pubmed_service import _keyword_relevance_score
        score = _keyword_relevance_score(
            title="Soil Moisture Monitoring with IoT Sensors in Agriculture",
            abstract="We deployed wireless soil moisture sensors across USDA field trial plots.",
            idea="soil moisture sensor for precision agriculture and USDA field trials",
        )
        assert score >= 6, f"On-topic paper scored {score} — expected >= 6"

    def test_score_off_topic_paper_below_threshold(self):
        from app.services.pubmed_service import _keyword_relevance_score
        score = _keyword_relevance_score(
            title="Hublink: SD Card-Free Neural Data Acquisition for Wireless Brain Implants",
            abstract="We describe a cloud-based platform for neuroscience laboratory data.",
            idea="soil moisture sensor for precision agriculture",
        )
        assert score < 6, f"Off-topic paper scored {score} — expected < 6"

    def test_no_idea_text_never_filters(self):
        from app.services.pubmed_service import _keyword_relevance_score
        score = _keyword_relevance_score(
            title="Some random unrelated paper",
            abstract="Nothing to do with anything.",
            idea="",
        )
        assert score == 10, "No idea text → score must be 10 (pass everything)"

    def test_off_topic_null_pmid_citation_dropped_by_relevance_gate(self):
        """A null-PMID neuroscience paper (LLM-recalled) is dropped by the relevance gate
        when the product is a soil sensor — no keyword overlap → score < 6."""
        from app.services.pubmed_service import filter_literature_citations
        # null PMID: LLM recalled this from memory for the wrong product
        citation = {
            "pmid": "",
            "title": "Hublink: SD Card-Free Neural Data Acquisition for Wireless Brain Implants",
            "authors": "Bhatt et al.",
            "journal": "eLife",
            "year": "2024",
            "relevance": "Some relevance claim.",
        }
        # OpenAlex finds it (it's a real paper), but it's off-topic for soil sensors
        fake_verified = {
            "title":        "Hublink: SD Card-Free Neural Data Acquisition for Wireless Brain Implants",
            "authors":      "Bhatt et al.",
            "journal":      "eLife",
            "year":         "2024",
            "doi":          "10.7554/eLife.xxx",
            "url":          "https://doi.org/10.7554/eLife.xxx",
            "verified_via": "openAlex",
        }
        with patch("app.services.pubmed_service.resolve_via_openalex", return_value=fake_verified):
            result = filter_literature_citations(
                [citation],
                idea="soil moisture sensor for precision agriculture and USDA field trials",
                sub_expert_id="research_tool_non_clinical",
            )
        assert result == [], (
            f"Off-topic neuroscience paper verified via OpenAlex should still be dropped "
            f"by relevance gate when idea is soil sensor; got {result}"
        )

    def test_on_topic_citation_passes_relevance_gate(self):
        """An on-topic paper passes both PMID resolution and relevance gate."""
        from app.services.pubmed_service import filter_literature_citations
        citation = {
            "pmid": "23456789",
            "title": "Wireless Soil Moisture Sensors for USDA Field Monitoring",
            "authors": "Jones et al.",
            "journal": "Precision Agriculture",
            "year": "2023",
            "relevance": "Documents soil sensor adoption in precision agriculture.",
        }
        with patch("app.services.pubmed_service.resolve_pmid", return_value={
            "pmid": "23456789",
            "title": "Wireless Soil Moisture Sensors for USDA Field Monitoring",
            "authors": "Jones et al.",
            "journal": "Precision Agriculture",
            "year": "2023",
            "abstract": "We deployed wireless soil moisture sensors across USDA field trial plots to monitor soil water content in precision agriculture settings.",
            "url": "https://pubmed.ncbi.nlm.nih.gov/23456789/",
        }):
            result = filter_literature_citations(
                [citation],
                idea="soil moisture sensor for precision agriculture and USDA field trials",
                sub_expert_id="research_tool_non_clinical",
            )
        assert len(result) == 1, f"On-topic paper should pass; got {result}"
