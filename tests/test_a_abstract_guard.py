"""Part A abstract guard tests: _verify_claims_against_abstract and integration
with filter_literature_citations via a mocked resolve_pmid."""
import pytest
from unittest.mock import patch

from app.services.pubmed_service import (
    _verify_claims_against_abstract,
    filter_literature_citations,
)


# ---------------------------------------------------------------------------
# Unit tests for _verify_claims_against_abstract
# ---------------------------------------------------------------------------

def test_no_stats_in_relevance_passes_through():
    relevance = "This paper describes methods for protein folding analysis."
    abstract  = "We investigated structural dynamics of folded proteins."
    assert _verify_claims_against_abstract(relevance, abstract) == relevance


def test_stat_present_in_abstract_passes():
    relevance = "Authors found 42% reduction in tumor volume."
    abstract  = "Results showed a 42% reduction in tumor volume at 8 weeks."
    assert _verify_claims_against_abstract(relevance, abstract) == relevance


def test_stat_absent_from_abstract_flagged():
    relevance = "Study reports 87% sensitivity for early detection."
    abstract  = "A novel diagnostic assay was evaluated in 200 patients."
    result = _verify_claims_against_abstract(relevance, abstract)
    assert result == "claim not verifiable from abstract"


def test_dollar_stat_absent_flagged():
    relevance = "Market estimated at $2.4M annually."
    abstract  = "We assessed cost-effectiveness in a retrospective cohort."
    result = _verify_claims_against_abstract(relevance, abstract)
    assert result == "claim not verifiable from abstract"


def test_empty_abstract_passes_through():
    """No abstract available → don't penalise the citation."""
    relevance = "Study shows 15% improvement."
    result = _verify_claims_against_abstract(relevance, "")
    assert result == relevance


def test_empty_relevance_passes_through():
    result = _verify_claims_against_abstract("", "Large abstract text here 42% blah.")
    assert result == ""


def test_case_insensitive_match():
    relevance = "Found 15% improvement in outcomes."
    abstract  = "The intervention yielded 15% IMPROVEMENT in patient outcomes."
    assert _verify_claims_against_abstract(relevance, abstract) == relevance


# ---------------------------------------------------------------------------
# Integration: filter_literature_citations with mocked resolve_pmid
# ---------------------------------------------------------------------------

_REAL_ABSTRACT = (
    "A randomised controlled trial of 320 patients demonstrated a 42% reduction "
    "in adverse events. Cost per patient was $1,200. Follow-up was 48 hours."
)

_RESOLVED_WITH_MATCH = {
    "pmid":     "12345678",
    "title":    "RCT on adverse event reduction",
    "authors":  "Smith et al.",
    "journal":  "NEJM",
    "year":     "2022",
    "abstract": _REAL_ABSTRACT,
    "url":      "https://pubmed.ncbi.nlm.nih.gov/12345678/",
}

_RESOLVED_NO_ABSTRACT = {**_RESOLVED_WITH_MATCH, "abstract": ""}


def _make_citation(pmid="12345678", title="RCT on adverse event reduction", relevance=""):
    return {"pmid": pmid, "title": title, "relevance": relevance}


def test_integration_stat_matches_abstract_kept_unchanged():
    citation = _make_citation(relevance="Study shows 42% reduction in adverse events.")
    with patch("app.services.pubmed_service.resolve_pmid", return_value=_RESOLVED_WITH_MATCH):
        result = filter_literature_citations([citation], idea="cancer drug", sub_expert_id="oncology")
    assert len(result) == 1
    assert result[0]["relevance"] == "Study shows 42% reduction in adverse events."


def test_integration_fabricated_stat_flagged():
    citation = _make_citation(relevance="Authors report 99% cure rate.")
    with patch("app.services.pubmed_service.resolve_pmid", return_value=_RESOLVED_WITH_MATCH):
        result = filter_literature_citations([citation], idea="cancer drug", sub_expert_id="oncology")
    assert len(result) == 1
    assert result[0]["relevance"] == "claim not verifiable from abstract"


def test_integration_no_abstract_relevance_unchanged():
    citation = _make_citation(relevance="Authors report 99% cure rate.")
    with patch("app.services.pubmed_service.resolve_pmid", return_value=_RESOLVED_NO_ABSTRACT):
        result = filter_literature_citations([citation], idea="cancer drug", sub_expert_id="oncology")
    assert len(result) == 1
    # No abstract → can't verify → pass through unchanged
    assert result[0]["relevance"] == "Authors report 99% cure rate."


def test_integration_unresolvable_pmid_passes_through():
    citation = _make_citation(pmid="99999999", relevance="Describes novel assay.")
    with patch("app.services.pubmed_service.resolve_pmid", return_value=None):
        result = filter_literature_citations([citation], idea="cancer drug", sub_expert_id="oncology")
    assert len(result) == 1
    assert result[0]["relevance"] == "Describes novel assay."


def test_integration_no_pmid_passes_through():
    citation = {"pmid": "", "title": "Some paper", "relevance": "Qualitative findings."}
    with patch("app.services.pubmed_service.resolve_pmid") as mock_resolve:
        result = filter_literature_citations([citation], idea="cancer drug", sub_expert_id="oncology")
    mock_resolve.assert_not_called()
    assert len(result) == 1
