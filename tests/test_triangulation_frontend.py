"""
Triangulation + Monte Carlo + Sensitivity frontend rendering — source-inspection tests.

Verifies that renderPIReport() and downloadPDF() in app.html both contain the
logic to render the three-method triangulation, Monte Carlo envelope, and
sensitivity tornado. All tests are pure string/regex checks; no API key, no DB.
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


def _render_section(src: str) -> str:
    """Slice of app.html from renderPIReport up to downloadPDF."""
    start = src.find("function renderPIReport")
    end   = src.find("function downloadPDF")
    assert start != -1, "renderPIReport not found"
    assert end   != -1, "downloadPDF not found"
    return src[start:end]


def _pdf_section(src: str) -> str:
    """Slice of app.html from downloadPDF to end."""
    start = src.rfind("function downloadPDF")
    assert start != -1, "downloadPDF not found"
    return src[start:]


# ── Gate ─────────────────────────────────────────────────────────────────────

class TestTriangulationGate:

    def test_triangulation_field_read_in_render(self):
        src = _render_section(_app())
        assert "r.triangulation" in src, (
            "renderPIReport must read r.triangulation before rendering sizing methodology"
        )

    def test_triangulation_field_read_in_pdf(self):
        src = _pdf_section(_app())
        assert "r.triangulation" in src or "triangulation" in src, (
            "downloadPDF must render the triangulation section"
        )

    def test_methodology_transparency_heading(self):
        src = _render_section(_app())
        assert "Methodology Transparency" in src or "How We Got" in src, (
            "renderPIReport must include a 'Methodology Transparency' / 'How We Got Here' heading"
        )


# ── Three methods ─────────────────────────────────────────────────────────────

class TestTriangulationMethods:

    def test_bottom_up_key_read(self):
        src = _render_section(_app())
        assert "bottom_up" in src, (
            "renderPIReport must access r.triangulation.bottom_up"
        )

    def test_top_down_key_read(self):
        src = _render_section(_app())
        assert "top_down" in src, (
            "renderPIReport must access r.triangulation.top_down"
        )

    def test_value_based_key_read(self):
        src = _render_section(_app())
        assert "value_based" in src, (
            "renderPIReport must access r.triangulation.value_based"
        )

    def test_bottom_up_tier_breakdown_rendered(self):
        src = _render_section(_app())
        assert "tier_breakdown" in src, (
            "renderPIReport must render bottom_up.tier_breakdown to show the revenue split"
        )

    def test_wtp_derivation_rendered(self):
        src = _render_section(_app())
        assert "labor_value_per_lab_usd" in src or "wtp_mid_per_lab_usd" in src, (
            "renderPIReport must show the WTP derivation from value_based method"
        )

    def test_weights_displayed(self):
        src = _render_section(_app())
        assert "50%" in src and "25%" in src, (
            "renderPIReport must display the reconciliation weights (50%, 25%, 25%)"
        )

    def test_all_three_methods_in_pdf(self):
        src = _pdf_section(_app())
        assert "bottom_up" in src and "top_down" in src and "value_based" in src, (
            "downloadPDF must render all three triangulation methods"
        )


# ── Reconciliation ────────────────────────────────────────────────────────────

class TestReconciliation:

    def test_reconciled_key_read(self):
        src = _render_section(_app())
        assert "reconciled" in src, (
            "renderPIReport must access r.triangulation.reconciled"
        )

    def test_reconciled_estimate_label(self):
        src = _render_section(_app())
        assert "Reconciled" in src, (
            "renderPIReport must label the reconciled estimate explicitly"
        )

    def test_divergence_flag_handled(self):
        src = _render_section(_app())
        assert "divergence_flag" in src, (
            "renderPIReport must check divergence_flag and warn when methods diverge"
        )

    def test_divergence_note_rendered(self):
        src = _render_section(_app())
        assert "divergence_note" in src, (
            "renderPIReport must render divergence_note when flag is set"
        )

    def test_reconciled_in_pdf(self):
        src = _pdf_section(_app())
        assert "reconciled" in src and ("Reconciled" in src or "reconcil" in src.lower()), (
            "downloadPDF must render the reconciled estimate"
        )


# ── Monte Carlo ───────────────────────────────────────────────────────────────

class TestMonteCarlo:

    def test_monte_carlo_field_read(self):
        src = _render_section(_app())
        assert "monte_carlo" in src, (
            "renderPIReport must read r.triangulation.monte_carlo"
        )

    def test_p10_p50_p90_rendered(self):
        src = _render_section(_app())
        assert "_mc.p10" in src or "mc.p10" in src, (
            "renderPIReport must render P10 from the Monte Carlo result"
        )
        assert "_mc.p50" in src or "mc.p50" in src, (
            "renderPIReport must render P50 (median) from the Monte Carlo result"
        )
        assert "_mc.p90" in src or "mc.p90" in src, (
            "renderPIReport must render P90 from the Monte Carlo result"
        )

    def test_n_iterations_displayed(self):
        src = _render_section(_app())
        assert "n_iterations" in src, (
            "renderPIReport must show the number of Monte Carlo iterations"
        )

    def test_seed_displayed_for_reproducibility(self):
        src = _render_section(_app())
        assert "seed" in src and ("reproducible" in src or "Seed" in src), (
            "renderPIReport must display the MC seed and note it is reproducible"
        )

    def test_uncertain_parameters_listed(self):
        src = _render_section(_app())
        assert "uncertain_parameters" in src, (
            "renderPIReport must list the uncertain_parameters that were sampled"
        )

    def test_monte_carlo_heading_present(self):
        src = _render_section(_app())
        assert "Monte Carlo" in src, (
            "renderPIReport must include a 'Monte Carlo' heading"
        )

    def test_monte_carlo_in_pdf(self):
        src = _pdf_section(_app())
        assert "monte_carlo" in src and "Monte Carlo" in src, (
            "downloadPDF must render the Monte Carlo section"
        )

    def test_p10_p50_p90_in_pdf(self):
        src = _pdf_section(_app())
        assert "_pmc.p10" in src or "pmc.p10" in src, (
            "downloadPDF must render P10/P50/P90 from the Monte Carlo result"
        )


# ── Sensitivity tornado ───────────────────────────────────────────────────────

class TestSensitivityTornado:

    def test_sensitivity_field_read(self):
        src = _render_section(_app())
        assert "r.sensitivity" in src, (
            "renderPIReport must read r.sensitivity"
        )

    def test_sensitivity_heading_present(self):
        src = _render_section(_app())
        assert "Sensitivity" in src, (
            "renderPIReport must include a 'Sensitivity Analysis' heading"
        )

    def test_impact_usd_used_for_bar_width(self):
        src = _render_section(_app())
        assert "impact_usd" in src, (
            "renderPIReport must use impact_usd to compute tornado bar widths"
        )

    def test_impact_pct_displayed(self):
        src = _render_section(_app())
        assert "impact_pct" in src, (
            "renderPIReport must display impact_pct (percentage TAM swing) per parameter"
        )

    def test_tam_low_high_range_shown(self):
        src = _render_section(_app())
        assert "tam_low_usd" in src and "tam_high_usd" in src, (
            "renderPIReport must show the TAM low/high range per sensitivity parameter"
        )

    def test_top_8_sliced(self):
        src = _render_section(_app())
        assert "slice(0, 8)" in src or "slice(0,8)" in src, (
            "renderPIReport must show only the top 8 sensitivity drivers (slice(0,8))"
        )

    def test_sensitivity_in_pdf(self):
        src = _pdf_section(_app())
        assert "sensitivity" in src and "Sensitivity" in src, (
            "downloadPDF must render the sensitivity analysis section"
        )

    def test_pdf_shows_top_8(self):
        src = _pdf_section(_app())
        assert "slice(0,8)" in src or ".slice(0,8)" in src or "slice(0, 8)" in src, (
            "downloadPDF must also cap at 8 sensitivity drivers"
        )
