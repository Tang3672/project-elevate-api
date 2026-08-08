"""
A-02 — Mock mode watermark
===========================
Reports generated with sample data (model_version starting with "mock" or
mock_mode=True) must display a visible DEMO banner so they are never confused
with real intelligence reports.

Failure modes:
  1. A demo report is shared without any watermark — mistaken for real output.
  2. A real report accidentally shows a DEMO banner — undermines credibility.

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import re

import pytest


def _render(report: dict, **kwargs) -> str:
    from app.services.pdf_renderer import render_report_html
    return render_report_html(report, **kwargs)


def _strip_style(html: str) -> str:
    return re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL)


_MOCK_DIV_RE = re.compile(r"""<div[^>]*class=['"]mock-banner""")


def _has_mock_div(html: str) -> bool:
    """Return True if the HTML body contains a mock-banner div (not just the CSS rule)."""
    body = _strip_style(html)
    return bool(_MOCK_DIV_RE.search(body))


# ══════════════════════════════════════════════════════════════════════════════
# Banner presence
# ══════════════════════════════════════════════════════════════════════════════

class TestMockBannerPresence:

    def test_mock_model_version_shows_banner(self):
        html = _render({"model_version": "mock-1.0"})
        assert _has_mock_div(html), (
            "model_version='mock-1.0' must trigger the DEMO banner div"
        )

    def test_mock_prefix_case_insensitive(self):
        html = _render({"model_version": "MOCK-2.0"})
        assert _has_mock_div(html)

    def test_mock_mode_param_shows_banner(self):
        html = _render({}, mock_mode=True)
        assert _has_mock_div(html), (
            "mock_mode=True must inject the DEMO banner regardless of model_version"
        )

    def test_no_model_version_no_banner(self):
        html = _render({"executive_summary": "Strong commercial case."})
        assert not _has_mock_div(html)

    def test_live_model_version_no_banner(self):
        html = _render({"model_version": "claude-opus-4-8"})
        assert not _has_mock_div(html)

    def test_empty_model_version_no_banner(self):
        html = _render({"model_version": ""})
        assert not _has_mock_div(html)

    def test_none_model_version_no_banner(self):
        html = _render({"model_version": None})
        assert not _has_mock_div(html)

    def test_mock_mode_false_with_mock_version_still_shows_banner(self):
        """model_version detection overrides explicit mock_mode=False."""
        html = _render({"model_version": "mock-1.0"}, mock_mode=False)
        assert _has_mock_div(html)


# ══════════════════════════════════════════════════════════════════════════════
# Banner content
# ══════════════════════════════════════════════════════════════════════════════

class TestMockBannerContent:

    def test_banner_says_demo(self):
        html = _render({"model_version": "mock-1.0"})
        body = _strip_style(html)
        m = _MOCK_DIV_RE.search(body)
        assert m and "demo" in body[m.start():m.start() + 300].lower(), (
            "Mock banner must contain the word 'DEMO'"
        )

    def test_banner_warns_not_for_distribution(self):
        html = _render({"model_version": "mock-1.0"})
        body = _strip_style(html)
        m = _MOCK_DIV_RE.search(body)
        snippet = body[m.start():m.start() + 300].lower() if m else ""
        assert "distribution" in snippet or "not for" in snippet, (
            "Mock banner must warn the reader that the report is not for distribution"
        )

    def test_banner_has_role_alert(self):
        """Screen readers must recognize the banner as an alert."""
        html = _strip_style(_render({"model_version": "mock-1.0"}))
        assert 'role="alert"' in html or "role='alert'" in html

    def test_banner_appears_before_toc(self):
        """The DEMO banner must appear before the table of contents."""
        body = _strip_style(_render({"model_version": "mock-1.0",
                                     "executive_summary": "Sample opportunity."}))
        m = _MOCK_DIV_RE.search(body)
        toc_pos = body.find('<nav class="toc"')
        assert m and toc_pos != -1
        assert m.start() < toc_pos, (
            "DEMO banner must appear before the TOC so it's seen first when scrolling"
        )

    def test_banner_appears_after_cover(self):
        """Banner should come after the cover header, not before."""
        body = _strip_style(_render({"model_version": "mock-1.0"}))
        cover_pos = body.find('<header class="cover"')
        m = _MOCK_DIV_RE.search(body)
        assert cover_pos != -1 and m
        assert cover_pos < m.start()


# ══════════════════════════════════════════════════════════════════════════════
# Banner CSS exists (in style block)
# ══════════════════════════════════════════════════════════════════════════════

class TestMockBannerCss:

    def test_mock_banner_css_rule_exists(self):
        """The CSS must define .mock-banner regardless of mock mode."""
        html = _render({})
        m = re.search(r"<style[^>]*>(.*?)</style>", html, re.DOTALL)
        assert m, "No <style> block found"
        css = m.group(1)
        assert ".mock-banner" in css, (
            ".mock-banner CSS class must always be defined (banner relies on it)"
        )

    def test_mock_banner_css_has_background(self):
        html = _render({})
        m = re.search(r"\.mock-banner\s*\{([^}]+)\}", html, re.DOTALL)
        assert m, ".mock-banner CSS rule not found"
        rule = m.group(1)
        assert "background" in rule


# ══════════════════════════════════════════════════════════════════════════════
# Banner does not create a TOC entry or section id
# ══════════════════════════════════════════════════════════════════════════════

class TestMockBannerDoesNotPolluteToc:

    def test_banner_not_in_toc(self):
        html = _render({
            "model_version": "mock-1.0",
            "executive_summary": "Sample opportunity.",
        })
        m = re.search(r'<nav class="toc".*?</nav>', html, re.DOTALL)
        assert m, "TOC nav block not found"
        toc = m.group(0)
        assert not _MOCK_DIV_RE.search(toc), (
            "Mock banner div must not appear inside the TOC nav block"
        )

    def test_banner_has_no_section_id(self):
        html = _render({"model_version": "mock-1.0"})
        section_ids = re.findall(r'<div class="section[^"]*" id="([^"]+)"', html)
        for sid in section_ids:
            assert "mock" not in sid.lower(), (
                f"Section id {sid!r} must not reference mock — banner is not a navigable section"
            )
