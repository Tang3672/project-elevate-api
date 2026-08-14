"""
C.2 axis decision display — source-inspection tests.

Verifies that renderPIReport() and downloadPDF() in app.html both read
r.axis_decisions and render the selected-axes chips and the rejected-axes
exclusion list with reasons. All tests are pure string/regex checks against
the source file; no runtime, no API key.
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
    start = src.find("function renderPIReport")
    end   = src.find("function downloadPDF")
    assert start != -1 and end != -1
    return src[start:end]


def _pdf_section(src: str) -> str:
    start = src.rfind("function downloadPDF")
    assert start != -1
    return src[start:]


# ── Gate ─────────────────────────────────────────────────────────────────────

class TestAxisDecisionGate:

    def test_axis_decisions_field_read_in_render(self):
        src = _render_section(_app())
        assert "r.axis_decisions" in src, (
            "renderPIReport must read r.axis_decisions before rendering axis selection"
        )

    def test_axis_decisions_field_read_in_pdf(self):
        src = _pdf_section(_app())
        assert "r.axis_decisions" in src, (
            "downloadPDF must also render r.axis_decisions"
        )

    def test_segmentation_methodology_heading(self):
        src = _render_section(_app())
        assert "Segmentation Methodology" in src or "Which Axes We Used" in src, (
            "renderPIReport must include a segmentation methodology heading (C.2)"
        )

    def test_explanation_prose_present(self):
        src = _render_section(_app())
        assert "exclusion list" in src or "consultant" in src or "rejected" in src.lower(), (
            "renderPIReport must include prose explaining why the exclusion list signals expertise"
        )


# ── Selected axes ─────────────────────────────────────────────────────────────

class TestSelectedAxes:

    def test_selected_key_read(self):
        src = _render_section(_app())
        assert ".selected" in src or "['selected']" in src or '"selected"' in src, (
            "renderPIReport must read axis_decisions.selected"
        )

    def test_selected_count_displayed(self):
        src = _render_section(_app())
        assert "_sel.length" in src or "sel.length" in src, (
            "renderPIReport must display the count of selected axes (C.2)"
        )

    def test_selected_label_rendered(self):
        src = _render_section(_app())
        assert "ax.label" in src, (
            "renderPIReport must render ax.label for each selected axis chip"
        )

    def test_selected_family_color_coded(self):
        src = _render_section(_app())
        assert "ax.family" in src, (
            "renderPIReport must color-code chips by axis family (institutional vs. patient_demographic etc.)"
        )

    def test_lift_shown_when_available(self):
        src = _render_section(_app())
        assert "est_lift" in src, (
            "renderPIReport must show est_lift on selected axis chips when non-null"
        )

    def test_selected_in_pdf(self):
        src = _pdf_section(_app())
        assert "_psel" in src or "psel" in src or "selected" in src, (
            "downloadPDF must render selected axes"
        )


# ── Rejected axes ─────────────────────────────────────────────────────────────

class TestRejectedAxes:

    def test_rejected_key_read(self):
        src = _render_section(_app())
        assert ".rejected" in src or "['rejected']" in src or '"rejected"' in src, (
            "renderPIReport must read axis_decisions.rejected"
        )

    def test_rejected_count_displayed(self):
        src = _render_section(_app())
        assert "_rej.length" in src or "rej.length" in src, (
            "renderPIReport must display the count of rejected axes"
        )

    def test_rejection_reason_rendered(self):
        src = _render_section(_app())
        assert "ax.reason" in src, (
            "renderPIReport must render ax.reason for each rejected axis — this is the "
            "expertise signal the spec (C.2) requires"
        )

    def test_empty_reason_filtered(self):
        src = _render_section(_app())
        assert ".filter" in src and "reason" in src, (
            "renderPIReport must filter out rejected axes with no reason string "
            "before rendering the exclusion list"
        )

    def test_not_applicable_heading(self):
        src = _render_section(_app())
        assert "not applicable" in src.lower() or "Considered" in src, (
            "renderPIReport must label the rejected list 'Considered, not applicable' or similar"
        )

    def test_rejected_in_pdf(self):
        src = _pdf_section(_app())
        assert "_prej" in src or "prej" in src or "rejected" in src, (
            "downloadPDF must render rejected axes with their reasons"
        )

    def test_rejected_reason_in_pdf(self):
        src = _pdf_section(_app())
        assert "ax.reason" in src or "reason" in src, (
            "downloadPDF must render the rejection reason string for each excluded axis"
        )


# ── Placement ─────────────────────────────────────────────────────────────────

class TestPlacement:

    def test_axis_decisions_present_in_render(self):
        # Fix 1 removed the triangulation block entirely; this test now verifies
        # that axis_decisions is present and triangulation is gone from the renderer.
        src = _render_section(_app())
        assert src.find("r.axis_decisions") != -1, "r.axis_decisions must be present in renderPIReport"
        assert src.find("r.triangulation") == -1, (
            "r.triangulation must be absent — Fix 1 deleted the triangulation block"
        )

    def test_axis_decisions_present_in_pdf(self):
        # Same as above: triangulation gone, axis_decisions present.
        src = _pdf_section(_app())
        assert src.find("r.axis_decisions") != -1, "r.axis_decisions must be present in downloadPDF"
        assert src.find("r.triangulation") == -1, (
            "r.triangulation must be absent in downloadPDF — Fix 1 deleted the block"
        )
