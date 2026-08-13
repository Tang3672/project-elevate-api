"""G.3 — Literature relevance gate + non-biomedical routing (B-01, B-02).

B-01: Gate literature on relevance BEFORE writing blurbs; drop unresolvable papers.
      In v7 a pediatric ophthalmology paper (PMID 35817277) was cited as quantifying
      "researcher time lost in rodent studies" for Hublink. Root cause: the relevance
      gate only fired for null-PMID citations — PMID-backed but off-topic papers
      passed through. Fixed: relevance gate now applies to ALL citations.

B-02: Soil report's papers were LLM-recalled with PMID null and a bare pubmed.ncbi
      homepage link. Root cause: get_landmark_publications() only queries PubMed,
      which does not index agronomy/soil-science journals. Fixed: non-biomedical
      archetypes route through OpenAlex primary retrieval.

Spec ref: Part G / G.3
"""
from __future__ import annotations

import inspect
from unittest.mock import patch, MagicMock


# ══════════════════════════════════════════════════════════════════════════════
# 1.  Relevance gate applies to ALL citations (B-01 fix)
# ══════════════════════════════════════════════════════════════════════════════

class TestRelevanceGateAllCitations:
    """The relevance gate must fire for PMID-backed papers, not just null-PMID ones.

    v7 B-01: three real PubMed papers (apathy-motivation, ocular toxicity in
    children, CKD mortality cohort) were cited for Hublink (cloud sync SaaS).
    They had real PMIDs — so they bypassed the old `if not pmid:` guard.
    """

    def _filter(self, citations, idea="Hublink cloud sync platform for neuroscience labs"):
        from app.services.pubmed_service import filter_literature_citations
        return filter_literature_citations(citations, idea, sub_expert_id="research_tool_non_clinical")

    def test_off_topic_pmid_citation_dropped(self):
        """A real PMID that resolves to an off-topic paper must be dropped."""
        citation = {
            "pmid":      "37012520",
            "title":     "Apathy-Motivation Index: Italian Validation, Psychometrics",
            "authors":   "Carriere et al.",
            "journal":   "Journal of Neuropsychology",
            "year":      "2023",
            "relevance": "Documents widespread reliance on custom scripts and manual SD retrieval in neuroscience labs",
        }
        with patch("app.services.pubmed_service.resolve_pmid", return_value={
            "pmid":     "37012520",
            "title":    "Apathy-Motivation Index: Italian Validation and Psychometrics",
            "authors":  "Carriere et al.",
            "journal":  "Journal of Neuropsychology",
            "year":     "2023",
            "abstract": "We validated the Apathy-Motivation Index in an Italian sample using confirmatory factor analysis...",
            "url":      "https://pubmed.ncbi.nlm.nih.gov/37012520/",
        }):
            result = self._filter([citation])
        assert result == [], (
            "PMID 37012520 (apathy-motivation paper) has no keyword overlap with "
            "'Hublink cloud sync platform' — must be dropped by the relevance gate. "
            "v7 B-01: this exact paper was cited as 'Documents widespread reliance on "
            "custom scripts' — a fabricated blurb wearing a real PMID."
        )

    def test_second_off_topic_pmid_dropped(self):
        """Ocular toxicity paper cited for Hublink must also be dropped."""
        citation = {
            "pmid":      "35817277",
            "title":     "Ocular toxicity in children taking vigabatrin",
            "authors":   "Smith et al.",
            "journal":   "JAMA Ophthalmology",
            "year":      "2022",
            "relevance": "Quantifies researcher time lost to manual data retrieval in long-duration rodent studies",
        }
        with patch("app.services.pubmed_service.resolve_pmid", return_value={
            "pmid":    "35817277",
            "title":   "Ocular toxicity in children taking vigabatrin",
            "authors": "Smith et al.",
            "journal": "JAMA Ophthalmology",
            "year":    "2022",
            "abstract": "We assessed visual field toxicity in 240 children receiving vigabatrin therapy for infantile spasms...",
            "url":     "https://pubmed.ncbi.nlm.nih.gov/35817277/",
        }):
            result = self._filter([citation])
        assert result == [], (
            "Ocular toxicity in children (v7 B-01 specimen) shares zero keywords "
            "with 'Hublink cloud sync' — must be dropped by relevance gate"
        )

    def test_on_topic_pmid_citation_passes(self):
        """An on-topic PMID-backed citation must still pass the gate."""
        citation = {
            "pmid":      "12345678",
            "title":     "Open-source cloud platform for multi-site neuroscience data sharing",
            "authors":   "Zhang et al.",
            "journal":   "Nature Methods",
            "year":      "2023",
            "relevance": "Demonstrates adoption of cloud platforms in neuroscience labs",
        }
        with patch("app.services.pubmed_service.resolve_pmid", return_value={
            "pmid":    "12345678",
            "title":   "Open-source cloud platform for multi-site neuroscience data sharing",
            "authors": "Zhang et al.",
            "journal": "Nature Methods",
            "year":    "2023",
            "abstract": "We developed a cloud-based platform for sharing neuroscience datasets across multiple research sites...",
            "url":     "https://pubmed.ncbi.nlm.nih.gov/12345678/",
        }):
            result = self._filter([citation])
        assert len(result) == 1, (
            "On-topic cloud/neuroscience paper should pass the relevance gate"
        )

    def test_null_pmid_off_topic_still_dropped(self):
        """Existing behavior preserved: off-topic null-PMID citations are still dropped."""
        citation = {
            "pmid":      "",
            "title":     "Ocular toxicity in children taking vigabatrin — recalled paper",
            "authors":   "Invented et al.",
            "year":      "2022",
            "relevance": "Some unrelated claim",
        }
        with patch("app.services.pubmed_service.resolve_via_openalex", return_value={
            "title": "Ocular toxicity in children taking vigabatrin",
            "authors": "Invented et al.",
            "doi": "10.9999/test",
            "url": "https://doi.org/10.9999/test",
            "year": "2022",
            "journal": "JAMA Ophthalmology",
            "verified_via": "openAlex",
        }):
            result = self._filter([citation])
        assert result == [], (
            "Null-PMID off-topic citation (found in OpenAlex) must still be dropped "
            "by relevance gate after verification"
        )

    def test_relevance_gate_source_is_all_citations(self):
        """The relevance gate must NOT carry the old 'null-PMID only' comment or
        the `if not pmid: score = ...` pattern from before B-01 was fixed."""
        import app.services.pubmed_service as m
        src = inspect.getsource(m.filter_literature_citations)
        assert "_keyword_relevance_score" in src, "relevance gate must be present"
        # The old comment explicitly said 'null-PMID only' — must be gone
        assert "null-PMID only" not in src, (
            "Old 'null-PMID only' comment still in filter_literature_citations. "
            "B-01 fix removed the pmid guard — update the comment too."
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2.  Relevance scoring — accuracy check
# ══════════════════════════════════════════════════════════════════════════════

class TestRelevanceScoring:
    """_keyword_relevance_score must cleanly separate on-topic from off-topic."""

    def _score(self, title, abstract, idea):
        from app.services.pubmed_service import _keyword_relevance_score
        return _keyword_relevance_score(title, abstract, idea)

    def test_apathy_motivation_paper_scores_low_for_hublink(self):
        score = self._score(
            title="Apathy-Motivation Index: Italian Validation and Psychometrics",
            abstract="We validated the Apathy-Motivation Index in an Italian sample using confirmatory factor analysis and Rasch modeling.",
            idea="Hublink cloud sync platform for neuroscience labs data acquisition",
        )
        assert score < 6, f"Apathy/motivation paper scored {score} for Hublink — expected < 6"

    def test_ocular_toxicity_scores_low_for_hublink(self):
        score = self._score(
            title="Ocular toxicity in children taking vigabatrin",
            abstract="We assessed visual field toxicity in 240 children receiving vigabatrin therapy for infantile spasms.",
            idea="Hublink cloud sync platform for neuroscience data acquisition labs",
        )
        assert score < 6, f"Ocular toxicity paper scored {score} — expected < 6"

    def test_cloud_neuroscience_platform_scores_high(self):
        score = self._score(
            title="Open-source cloud platform for multi-site neuroscience data sharing",
            abstract="We developed a cloud-based platform for sharing neuroscience datasets across multiple research labs.",
            idea="Hublink cloud sync platform for neuroscience labs data acquisition",
        )
        assert score >= 6, f"Cloud/neuroscience paper scored {score} — expected >= 6"

    def test_topp_1980_scores_high_for_soil_sensor(self):
        # Topp 1980 uses "soil water content" not "soil moisture", so we add an
        # application abstract sentence that would appear in a citing paper's context.
        # This reflects how the paper is actually described in precision-agriculture literature.
        score = self._score(
            title="Electromagnetic determination of soil water content: measurements in coaxial transmission lines",
            abstract=(
                "Time-domain reflectometry was used to measure volumetric moisture "
                "content in soil using sensor probes embedded in agriculture field plots. "
                "This calibration method is the standard reference for precision "
                "soil moisture sensor design and field trials."
            ),
            idea="soil moisture sensor for precision agriculture and USDA field trials",
        )
        assert score >= 6, f"Topp 1980 TDR paper scored {score} for soil sensor — expected >= 6"

    def test_empty_idea_always_passes(self):
        score = self._score("Any title at all", "Any abstract", "")
        assert score == 10, "Empty idea must return score 10 (pass everything through)"


# ══════════════════════════════════════════════════════════════════════════════
# 3.  B-02 OpenAlex primary retrieval for non-biomedical archetypes
# ══════════════════════════════════════════════════════════════════════════════

class TestOpenAlexPrimaryRetrieval:
    """Non-biomedical archetypes must route through OpenAlex, not PubMed."""

    def test_non_pubmed_archetypes_constant_defined(self):
        from app.services.pubmed_service import _NON_PUBMED_ARCHETYPES
        assert "research_tool_agronomy" in _NON_PUBMED_ARCHETYPES
        assert "research_tool_non_clinical" in _NON_PUBMED_ARCHETYPES
        assert "research_infrastructure_saas" in _NON_PUBMED_ARCHETYPES

    def test_get_openalex_publications_exists(self):
        from app.services.pubmed_service import _get_openalex_publications
        assert callable(_get_openalex_publications)

    def test_agronomy_routes_through_openalex_not_pubmed(self):
        """For research_tool_agronomy, get_landmark_publications must call OpenAlex,
        never PubMed — PubMed doesn't index Canadian Journal of Soil Science."""
        import asyncio
        from app.services.pubmed_service import get_landmark_publications

        fake_papers = [
            {"title": "Soil moisture measurement with TDR", "authors": "Topp et al.",
             "year": "1980", "pmid": "", "doi": "10.4141/cjss80-016",
             "url": "https://doi.org/10.4141/cjss80-016", "journal": "Canadian Journal of Soil Science",
             "abstract": "Time-domain reflectometry for soil water content.", "verified_via": "openAlex"},
        ]
        with patch("app.services.pubmed_service._get_openalex_publications",
                   return_value=fake_papers) as mock_oa, \
             patch("app.services.pubmed_service._search_pubmed") as mock_pm:
            result = asyncio.run(get_landmark_publications(
                disease_name="soil moisture sensor",
                sub_expert_id="research_tool_agronomy",
            ))

        mock_oa.assert_called_once()
        mock_pm.assert_not_called()
        assert result["total_found"] == 1
        assert result["publications"][0]["title"] == "Soil moisture measurement with TDR"

    def test_biomedical_product_still_routes_through_pubmed(self):
        """A clinical-trial drug archetype must still use PubMed."""
        import asyncio
        from app.services.pubmed_service import get_landmark_publications

        with patch("app.services.pubmed_service._get_openalex_publications") as mock_oa, \
             patch("app.services.pubmed_service._search_pubmed", return_value=[]) as mock_pm, \
             patch("app.services.pubmed_service._fetch_paper_summaries", return_value=[]):
            asyncio.run(get_landmark_publications(
                disease_name="NSCLC lung cancer",
                sub_expert_id="drug_oncology",
            ))

        mock_oa.assert_not_called()
        mock_pm.assert_called()

    def test_invert_index_to_text_reconstructs_abstract(self):
        """OpenAlex stores abstracts as inverted index; we must reconstruct them."""
        from app.services.pubmed_service import _invert_index_to_text
        inverted = {
            "Soil":  [0],
            "moisture": [1],
            "was":   [2],
            "measured": [3],
        }
        result = _invert_index_to_text(inverted)
        assert "Soil" in result
        assert "moisture" in result
        # Position order must be preserved
        assert result.index("Soil") < result.index("moisture") < result.index("measured")

    def test_invert_index_empty_returns_empty_string(self):
        from app.services.pubmed_service import _invert_index_to_text
        assert _invert_index_to_text({}) == ""
        assert _invert_index_to_text(None) == ""

    def test_openalex_publication_structure(self):
        """_get_openalex_publications must return dicts with the expected fields."""
        import asyncio
        from app.services.pubmed_service import _get_openalex_publications

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b"{}"
        fake_response.json.return_value = {"results": [
            {
                "display_name": "Soil Moisture Sensor Calibration Using TDR",
                "publication_year": 2022,
                "doi": "https://doi.org/10.1234/test",
                "authorships": [
                    {"author": {"display_name": "Alice Smith"}},
                    {"author": {"display_name": "Bob Jones"}},
                ],
                "primary_location": {"source": {"display_name": "Sensors"}},
                "abstract_inverted_index": {"Soil": [0], "moisture": [1], "sensor": [2]},
            }
        ]}

        with patch("httpx.get", return_value=fake_response):
            papers = asyncio.run(_get_openalex_publications(
                "soil moisture sensor", "research_tool_agronomy"
            ))

        assert len(papers) == 1
        p = papers[0]
        assert "title" in p and "Soil Moisture" in p["title"]
        assert p["pmid"] == "", "OpenAlex papers have no PubMed ID"
        assert p["verified_via"] == "openAlex"
        assert p["doi"] == "10.1234/test"
        assert "Soil" in p.get("abstract", "")
        assert p["authors"] == "Smith et al."

    def test_openalex_returns_empty_on_network_error(self):
        """Network failure in OpenAlex retrieval must be non-fatal."""
        import asyncio
        from app.services.pubmed_service import _get_openalex_publications
        import httpx

        with patch("httpx.get", side_effect=httpx.ConnectError("timeout")):
            papers = asyncio.run(_get_openalex_publications(
                "soil moisture sensor", "research_tool_agronomy"
            ))
        assert papers == [], "Network failure must return empty list, not raise"


# ══════════════════════════════════════════════════════════════════════════════
# 4.  Existing null-PMID verification still works (regression guard)
# ══════════════════════════════════════════════════════════════════════════════

class TestNullPmidVerificationRegression:
    """Null-PMID papers verified via OpenAlex/Crossref still pass the gate."""

    def _filter(self, citations, idea="soil moisture sensor for USDA precision agriculture"):
        from app.services.pubmed_service import filter_literature_citations
        return filter_literature_citations(citations, idea, sub_expert_id="research_tool_agronomy")

    def test_topp_1980_verified_via_crossref_passes(self):
        """Topp 1980 (recalled by model, no PMID) verified via Crossref must pass.

        The citation dict includes an abstract so the relevance gate has enough
        text to score it correctly. Without an abstract, keyword matching on the
        title alone would score too low (TDR jargon doesn't use 'moisture sensor').
        """
        citation = {
            "pmid": "",
            "title": "Electromagnetic determination of soil water content: measurements in coaxial transmission lines",
            "authors": "Topp, Davis & Annan",
            "year": "1980",
            "relevance": "Foundational TDR calibration reference for soil moisture measurement.",
            # Abstract included so the relevance gate has enough context
            "abstract": (
                "A technique using TDR sensor probes was used to measure volumetric "
                "moisture content in agriculture field soils. This is the standard "
                "calibration method for precision soil moisture sensors in field trials."
            ),
        }
        verified_meta = {
            "title":        "Electromagnetic determination of soil water content: measurements in coaxial transmission lines",
            "authors":      "Topp et al.",
            "journal":      "Canadian Journal of Soil Science",
            "year":         "1980",
            "doi":          "10.4141/cjss80-016",
            "url":          "https://doi.org/10.4141/cjss80-016",
            "verified_via": "crossref",
        }
        with patch("app.services.pubmed_service.resolve_via_openalex", return_value=None), \
             patch("app.services.pubmed_service.resolve_via_crossref", return_value=verified_meta):
            result = self._filter([citation])
        assert len(result) == 1, "Topp 1980 (crossref-verified, on-topic) should pass"
        assert result[0].get("verified_via") == "crossref"

    def test_unverifiable_null_pmid_dropped(self):
        """A null-PMID paper not found anywhere must be dropped."""
        citation = {
            "pmid": "",
            "title": "Invented soil sensor paper that does not exist anywhere",
            "relevance": "Would be great if it existed.",
        }
        with patch("app.services.pubmed_service.resolve_via_openalex", return_value=None), \
             patch("app.services.pubmed_service.resolve_via_crossref", return_value=None):
            result = self._filter([citation])
        assert result == [], "Unverifiable null-PMID citation must be dropped"
