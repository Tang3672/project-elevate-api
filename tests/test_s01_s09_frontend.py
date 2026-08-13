"""
S-01…S-09 frontend rendering — source-inspection tests.

Verifies that the web renderer (renderPIReport in app.html) and the jsPDF
renderer both contain the logic to render each strategic section.  All tests
are pure string/regex checks against the source file; no runtime or API key.
"""

from __future__ import annotations

import os
import re


def _app() -> str:
    path = os.path.normpath(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "ProjectElevate-Frontend", "app.html"
        )
    )
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── Chapter 8 gate ────────────────────────────────────────────────────────────

class TestChapter8Gate:

    def test_chapter_8_heading_present(self):
        src = _app()
        assert "Strategic Intelligence" in src, (
            "renderPIReport must emit a 'Strategic Intelligence' chapter "
            "for S-01…S-09 content"
        )

    def test_chapter_8_guarded_by_content_check(self):
        src = _app()
        assert "_hasStrategicContent" in src, (
            "Chapter 8 must be conditionally rendered — only when at least one "
            "S-section field is present"
        )

    def test_chapter_8_uses_chapter_header(self):
        src = _app()
        # B-07: hardcoded '8' replaced with ++_sec counter; check the actual pattern
        assert "chapterHeader(++_sec, 'Strategic Intelligence'" in src, (
            "Chapter 8 must use chapterHeader(++_sec, ...) so B-07 sequential "
            "numbering applies after suppressed sections"
        )


# ── S-01 Evidence Base ────────────────────────────────────────────────────────

class TestS01EvidenceBase:

    def test_evidence_base_rendered(self):
        src = _app()
        assert "evidence_base" in src, (
            "renderPIReport must reference r.evidence_base (S-01)"
        )

    def test_evidence_gap_block_rendered(self):
        src = _app()
        assert "evidence_gap_block" in src, (
            "S-01 gap block must be rendered when primary research is absent"
        )

    def test_source_types_rendered(self):
        src = _app()
        assert "source_types_used" in src, (
            "S-01 must render source_types_used list"
        )


# ── S-02 Value Driver Ranking ─────────────────────────────────────────────────

class TestS02ValueDriverRanking:

    def test_value_driver_ranking_field_read(self):
        src = _app()
        assert "value_driver_ranking" in src, (
            "renderPIReport must read r.value_driver_ranking (S-02)"
        )

    def test_relative_importance_rendered(self):
        src = _app()
        assert "relative_importance" in src, (
            "S-02 table must render the relative_importance column"
        )

    def test_product_implication_rendered(self):
        src = _app()
        assert "product_implication" in src, (
            "S-02 table must render the product_implication column"
        )


# ── S-03 Segment Fit Table ────────────────────────────────────────────────────

class TestS03SegmentFitTable:

    def test_segment_fit_table_field_read(self):
        src = _app()
        assert "segment_fit_table" in src, (
            "renderPIReport must read r.segment_fit_table (S-03)"
        )

    def test_non_target_distinguished(self):
        src = _app()
        assert "non-target" in src.lower() or "nontarget" in src.lower(), (
            "S-03 renderer must distinguish Explicit non-target rows visually"
        )

    def test_strategic_stance_rendered(self):
        src = _app()
        assert "strategic_stance" in src, (
            "S-03 must render the strategic_stance column"
        )


# ── S-04 Feature Investment Posture ──────────────────────────────────────────

class TestS04FeatureInvestmentPosture:

    def test_feature_investment_posture_field_read(self):
        src = _app()
        assert "feature_investment_posture" in src, (
            "renderPIReport must read r.feature_investment_posture (S-04)"
        )

    def test_exclude_posture_distinguished(self):
        src = _app()
        # Check that 'Exclude' posture gets different styling
        m = re.search(
            r"posture.*?[Ee]xclude.*?Color|[Ee]xclude.*?posture.*?Color|"
            r"isExclude|is_exclude",
            src, re.DOTALL,
        )
        assert m, (
            "S-04 renderer must distinguish Exclude posture rows with distinct color"
        )

    def test_feature_area_rendered(self):
        src = _app()
        assert "feature_area" in src, (
            "S-04 must render the feature_area column"
        )


# ── S-05 Pricing Model Analysis ───────────────────────────────────────────────

class TestS05PricingModelAnalysis:

    def test_pricing_model_analysis_field_read(self):
        src = _app()
        assert "pricing_model_analysis" in src, (
            "renderPIReport must read r.pricing_model_analysis (S-05)"
        )

    def test_model_comparison_rendered(self):
        src = _app()
        assert "model_comparison" in src, (
            "S-05 must render the model_comparison table"
        )

    def test_structural_risk_rendered(self):
        src = _app()
        assert "structural_risk" in src, (
            "S-05 contextual_analysis must render the structural_risk column"
        )

    def test_recommended_stance_distinguished(self):
        src = _app()
        assert "Recommended" in src or "recommended" in src, (
            "S-05 must distinguish Recommended rows in the model_comparison table"
        )


# ── S-06 Adversarial Review ───────────────────────────────────────────────────

class TestS06AdversarialReview:

    def test_adversarial_review_field_read(self):
        src = _app()
        assert "adversarial_review" in src, (
            "renderPIReport must read r.adversarial_review (S-06)"
        )

    def test_structural_risk_in_adversarial(self):
        src = _app()
        # structural_risk appears in both S-05 and S-06
        assert src.count("structural_risk") >= 2, (
            "structural_risk must appear in both S-05 pricing and S-06 adversarial sections"
        )

    def test_what_would_change_this_rendered(self):
        src = _app()
        assert "what_would_change_this" in src, (
            "S-06 adversarial review must render the what_would_change_this field"
        )

    def test_adversarial_review_in_pdf_renderer(self):
        src = _app()
        assert "adversarial_review" in src and "Adversarial Review" in src, (
            "PDF renderer must also render the S-06 adversarial review section"
        )


# ── S-07 Positioning Statement ────────────────────────────────────────────────

class TestS07PositioningStatement:

    def test_positioning_statement_field_read(self):
        src = _app()
        assert "positioning_statement" in src, (
            "renderPIReport must read r.positioning_statement (S-07)"
        )

    def test_positioning_statement_in_pdf(self):
        src = _app()
        # Make sure it appears in the PDF section (after the heading function
        # definitions which are higher up in the file)
        pdf_section = src[src.rfind("function downloadPDF"):]
        assert "positioning_statement" in pdf_section, (
            "PDF renderer must also render r.positioning_statement (S-07)"
        )


# ── S-08 Strategic Risks ──────────────────────────────────────────────────────

class TestS08StrategicRisks:

    def test_strategic_risks_field_read(self):
        src = _app()
        assert "strategic_risks" in src, (
            "renderPIReport must read r.strategic_risks (S-08)"
        )

    def test_strategic_risks_in_pdf(self):
        src = _app()
        pdf_section = src[src.rfind("function downloadPDF"):]
        assert "strategic_risks" in pdf_section, (
            "PDF renderer must also render r.strategic_risks (S-08)"
        )


# ── S-09 Guiding Question ─────────────────────────────────────────────────────

class TestS09GuidingQuestion:

    def test_guiding_question_field_read(self):
        src = _app()
        assert "guiding_question" in src, (
            "renderPIReport must read r.guiding_question (S-09)"
        )

    def test_guiding_question_in_pdf(self):
        src = _app()
        pdf_section = src[src.rfind("function downloadPDF"):]
        assert "guiding_question" in pdf_section, (
            "PDF renderer must also render r.guiding_question (S-09)"
        )

    def test_guiding_question_visually_prominent(self):
        src = _app()
        # Should have a border or highlight — check for border styling near guiding_question
        m = re.search(
            r"guiding_question.*?border|border.*?guiding_question",
            src, re.DOTALL,
        )
        assert m, (
            "Guiding question must be visually prominent (bordered/highlighted) "
            "since it is the single decision test the team applies to every choice"
        )
