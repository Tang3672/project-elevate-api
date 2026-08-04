"""
B-09 — Literature relevance gate
=================================
Off-domain papers (DESeq2, STRING protein networks, clinical trials) must not
appear in the literature_citations of a non-clinical research tool report.

The gate is a pure function (filter_literature_citations) — no network, no DB.
"""

from __future__ import annotations
import pytest
from app.services.pubmed_service import filter_literature_citations, _is_non_clinical_product


# ── helpers ────────────────────────────────────────────────────────────────────

def _cit(title: str, relevance: str = "") -> dict:
    return {"pmid": "99999999", "title": title, "authors": "Smith J et al.",
            "journal": "J Test", "year": 2024, "relevance": relevance}


HUBLINK_IDEA = "Hublink: a non-clinical wearable data platform for academic PIs."
RT_EXPERT    = "research_tool_non_clinical"
DRUG_EXPERT  = "drug_amr"


# ── _is_non_clinical_product ───────────────────────────────────────────────────

class TestIsNonClinicalProduct:

    def test_research_tool_non_clinical_matches(self):
        assert _is_non_clinical_product("research_tool_non_clinical") is True

    def test_prefix_match(self):
        assert _is_non_clinical_product("research_tool_genomics") is True

    def test_non_clinical_in_middle(self):
        assert _is_non_clinical_product("lab_non_clinical_software") is True

    def test_drug_does_not_match(self):
        assert _is_non_clinical_product("drug_amr") is False

    def test_device_does_not_match(self):
        assert _is_non_clinical_product("device_cardiovascular") is False

    def test_empty_does_not_match(self):
        assert _is_non_clinical_product("") is False


# ── filter_literature_citations — off-domain signals ─────────────────────────

class TestB09OffDomainRejection:

    def test_deseq2_paper_blocked(self):
        cits = [_cit("DESeq2: Moderated estimation of fold change and dispersion for RNA-seq data")]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        assert result == [], "DESeq2 (RNA-seq tool) must be blocked for a wearable data logger"

    def test_string_protein_network_blocked(self):
        cits = [_cit("STRING v10: Protein-protein interaction networks, integrated over the tree of life")]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        assert result == [], "STRING protein-protein interaction paper must be blocked for a data logger"

    def test_clinical_trial_paper_blocked(self):
        cits = [_cit("A randomized controlled trial of wearable sensors in cardiac patients")]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        assert result == [], "Randomized controlled trial must be blocked for a non-clinical research tool"

    def test_chemotherapy_paper_blocked(self):
        cits = [_cit("Chemotherapy outcomes in advanced breast cancer: a phase III trial")]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        assert result == [], "Chemotherapy paper must be blocked for a non-clinical research tool"

    def test_gene_expression_blocked(self):
        cits = [_cit("Genome-wide gene expression profiling using microarray analysis")]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        assert result == [], "Gene expression paper must be blocked"

    def test_crispr_paper_blocked(self):
        cits = [_cit("CRISPR-Cas9-mediated genome editing in human pluripotent stem cells")]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        assert result == [], "CRISPR paper must be blocked for a data logger"


# ── filter_literature_citations — on-domain papers pass ──────────────────────

class TestB09OnDomainPassthrough:

    def test_redcap_paper_passes(self):
        cits = [_cit(
            "REDCap — a metadata-driven methodology and workflow process for providing translational research informatics support",
            relevance="Demonstrates citation-driven adoption in research software tools"
        )]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        assert len(result) == 1, "REDCap (research software) must pass for a research tool"

    def test_fiji_paper_passes(self):
        cits = [_cit(
            "Fiji: an open-source platform for biological-image analysis",
            relevance="Citation-adoption model for open-source research tools"
        )]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        assert len(result) == 1, "Fiji (research tool) must pass"

    def test_wearable_sensor_paper_passes(self):
        cits = [_cit(
            "Wearable IoT sensors for continuous physiological monitoring in research settings",
            relevance="Directly describes the product domain"
        )]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        assert len(result) == 1, "Wearable sensor paper must pass for a wearable platform"

    def test_open_source_software_adoption_passes(self):
        cits = [_cit(
            "Citation patterns in open-source scientific software: a cross-domain analysis",
            relevance="Framework for measuring citation-driven adoption of research tools"
        )]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        assert len(result) == 1, "Software adoption paper must pass"


# ── filter is a no-op for clinical products ───────────────────────────────────

class TestB09ClinicalProductPassthrough:

    def test_deseq2_passes_for_drug_product(self):
        """Drug pipeline products are never filtered — all citations pass through."""
        cits = [_cit("DESeq2: Moderated estimation of fold change and dispersion for RNA-seq data")]
        result = filter_literature_citations(cits, "A novel antibiotic for drug-resistant infections.", DRUG_EXPERT)
        assert len(result) == 1, "Gate must not fire for drug products"

    def test_rct_passes_for_drug_product(self):
        cits = [_cit("A randomized controlled trial of novel antibiotic in community-acquired pneumonia")]
        result = filter_literature_citations(
            cits, "A novel antibiotic for drug-resistant infections.", DRUG_EXPERT
        )
        assert len(result) == 1, "RCT must pass for a drug product"

    def test_empty_expert_id_passes_all(self):
        """No sub_expert_id → gate never fires."""
        cits = [
            _cit("DESeq2: Moderated estimation of fold change"),
            _cit("STRING protein-protein interaction networks"),
        ]
        result = filter_literature_citations(cits, HUBLINK_IDEA, "")
        assert len(result) == 2


# ── product-owns-signal exception ─────────────────────────────────────────────

class TestB09ProductOwnsSignal:

    def test_rna_seq_tool_may_cite_deseq2(self):
        """
        If the product idea itself mentions RNA-seq, DESeq2 is on-domain.
        The gate must not block it.
        """
        rna_idea = "An RNA-seq pipeline tool for academic bioinformatics labs, improving on DESeq2 workflows."
        cits = [_cit("DESeq2: Moderated estimation of fold change and dispersion for RNA-seq data")]
        result = filter_literature_citations(cits, rna_idea, RT_EXPERT)
        assert len(result) == 1, (
            "RNA-seq paper must pass when product idea explicitly mentions RNA-seq"
        )

    def test_protein_tool_may_cite_string(self):
        """Protein interaction tool may cite STRING."""
        ppi_idea = "A protein-protein interaction visualization platform for structural biologists."
        cits = [_cit("STRING v10: Protein-protein interaction networks, integrated over the tree of life")]
        result = filter_literature_citations(cits, ppi_idea, RT_EXPERT)
        assert len(result) == 1, (
            "Protein network paper must pass when product idea mentions protein-protein interactions"
        )


# ── empty / edge cases ────────────────────────────────────────────────────────

class TestB09EdgeCases:

    def test_empty_citations_returns_empty(self):
        assert filter_literature_citations([], HUBLINK_IDEA, RT_EXPERT) == []

    def test_mixed_list_partial_filter(self):
        cits = [
            _cit("REDCap — metadata-driven methodology for software"),
            _cit("DESeq2: RNA-seq differential expression analysis"),
            _cit("Fiji: an open-source platform for biological-image analysis"),
            _cit("A randomized controlled trial of novel therapies"),
        ]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        titles = [c["title"] for c in result]
        assert any("REDCap" in t for t in titles), "REDCap must pass"
        assert any("Fiji" in t for t in titles), "Fiji must pass"
        assert not any("DESeq2" in t for t in titles), "DESeq2 must be blocked"
        assert not any("randomized controlled trial" in t for t in titles), "RCT must be blocked"

    def test_citation_with_missing_title_passes(self):
        """Citations with no title must not crash and should pass through."""
        cits = [{"pmid": "123", "title": None, "authors": "Smith J", "year": 2024}]
        result = filter_literature_citations(cits, HUBLINK_IDEA, RT_EXPERT)
        assert len(result) == 1, "Citation with None title must pass (no title to match against)"
