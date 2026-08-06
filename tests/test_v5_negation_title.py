"""
Spec v5 Part B + C-04 — negation titles and medical vocabulary in non-medical reports.

Part B: the title must bind to product_name, never to a disease indication.
        The phrase "not applicable" must not appear anywhere in a report for
        a product that simply has no clinical indication.

C-04:  medical/clinical vocabulary ("disease-relevant", "therapeutic area",
       "MEDICAL MARKET INTELLIGENCE REPORT") must not appear in the generated
       content of a non-clinical, non-medical-device product.

These are source-inspection tests against service files, fixtures, and the
frontend; no API key required.
"""

from __future__ import annotations

import json
import os
import re

_SRC_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "app")
)
_TEST_ROOT = os.path.dirname(__file__)

_NEGATION_PREFIXES = (
    "not applicable",
    "not disease",
    "no clinical",
    "n/a —",
    "not a ",
    "no direct",
    "not disease-specific",
    "no disease",
)

_MEDICAL_TOKENS_FOR_NON_MEDICAL = [
    "disease-relevant",
    "therapeutic area",
    "clinical indication",
    "antimicrobial",
    "pharmacological mechanism",
    "payer uptake",
    "guideline inclusion",
    "initial label",
    "reimbursement",          # in the context of non-medical output
    "cdc/seer epidemiology",
    "drg",
    "iqvia forecast",
]


def _app_html() -> str:
    path = os.path.normpath(
        os.path.join(_TEST_ROOT, "..", "..", "ProjectElevate-Frontend", "app.html")
    )
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestNegationTitleBan:

    def test_pdf_renderer_strips_negation_prefixes(self):
        """pdf_renderer.py must apply _NEGATION_PREFIXES substitution."""
        with open(os.path.join(_SRC_ROOT, "services", "pdf_renderer.py"), encoding="utf-8") as f:
            src = f.read()
        assert "_NEGATION_PREFIXES" in src, (
            "pdf_renderer.py must define _NEGATION_PREFIXES and strip negation titles"
        )

    def test_pdf_renderer_negation_is_regex(self):
        src_path = os.path.join(_SRC_ROOT, "services", "pdf_renderer.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        m = re.search(r"_NEGATION_PREFIXES\s*=\s*re\.compile", src)
        assert m, (
            "_NEGATION_PREFIXES must be a compiled regex so all variants are caught, "
            "not a tuple of plain strings"
        )

    def test_negation_prefixes_cover_all_observed_variants(self):
        """The _NEGATION_PREFIXES pattern must cover at least the five observed variants."""
        src_path = os.path.join(_SRC_ROOT, "services", "pdf_renderer.py")
        with open(src_path, encoding="utf-8") as f:
            src = f.read()
        # Extract the compiled pattern string
        m = re.search(r"_NEGATION_PREFIXES\s*=\s*re\.compile\s*\(([^)]+)\)", src, re.DOTALL)
        if not m:
            return  # covered by previous test
        pattern_src = m.group(1).lower()
        for frag in ("not applicable", "no clinical", "not disease"):
            assert frag in pattern_src or frag.replace(" ", ".") in pattern_src, (
                f"_NEGATION_PREFIXES must cover '{frag}' — one of the five observed variants"
            )

    def test_frontend_title_uses_product_name_not_indication(self):
        """renderPIReport must use product_name (not disease_intelligence.condition) for the title."""
        src = _app_html()
        render_fn = src[src.find("function renderPIReport"):src.find("function downloadPDF")]
        assert "r.product_name" in render_fn, (
            "renderPIReport must derive the report title from r.product_name, not a disease field"
        )

    def test_hublink_fixture_product_name_is_positive(self):
        fixture_path = os.path.join(_TEST_ROOT, "fixtures", "hublink.json")
        if not os.path.exists(fixture_path):
            return
        with open(fixture_path, encoding="utf-8") as f:
            data = json.load(f)
        name = (data.get("product_name") or "").lower().strip()
        for prefix in _NEGATION_PREFIXES:
            assert not name.startswith(prefix), (
                f"hublink.json product_name starts with negation prefix {prefix!r}: {name!r}"
            )

    def test_alignment_service_does_not_hardcode_not_applicable_title(self):
        """alignment_service.py must not contain 'not applicable' as a literal title."""
        svc_path = os.path.join(_SRC_ROOT, "services", "alignment_service.py")
        with open(svc_path, encoding="utf-8") as f:
            src = f.read()
        # Check that "not applicable" only appears in exclusion/stub contexts, not in title binding
        for m in re.finditer(r'["\']([^"\']*not applicable[^"\']*)["\']', src, re.I):
            ctx = src[max(0, m.start()-200):m.end()+200]
            assert "title" not in ctx.lower()[:200] or "inapplicable" in ctx.lower(), (
                f"alignment_service.py binds 'not applicable' near a title field: {m.group(0)!r}"
            )


class TestMedicalTokensInNonMedical:
    """C-04: medical vocabulary must not appear in generated content for non-clinical products."""

    def test_archetype_manifest_bans_clinical_vocab_for_research_tool(self):
        """ProductArchetype.RESEARCH_TOOL_NON_CLINICAL must have a non-empty banned_vocabulary."""
        from app.services.product_archetype import ProductArchetype, get_manifest
        manifest = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert len(manifest.banned_vocabulary) > 0, (
            "RESEARCH_TOOL_NON_CLINICAL must have a banned_vocabulary to enforce C-04"
        )

    def test_archetype_manifest_bans_therapeutic_area_for_research_tool(self):
        from app.services.product_archetype import ProductArchetype, get_manifest
        manifest = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        banned = {v.lower() for v in manifest.banned_vocabulary}
        assert any("therapeutic" in b for b in banned), (
            "RESEARCH_TOOL_NON_CLINICAL banned_vocabulary must include 'therapeutic area' variants"
        )

    def test_archetype_manifest_bans_disease_relevant_for_research_tool(self):
        from app.services.product_archetype import ProductArchetype, get_manifest
        manifest = get_manifest(ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        banned = {v.lower() for v in manifest.banned_vocabulary}
        assert any("disease" in b for b in banned) or any("clinical indication" in b for b in banned), (
            "RESEARCH_TOOL_NON_CLINICAL banned_vocabulary must ban 'disease-relevant' or "
            "'clinical indication' — these appeared in v5 agronomy output (C-04)"
        )

    def test_validate_report_catches_medical_token_in_research_tool(self):
        from app.services.product_archetype import ProductArchetype, validate_report_dict
        bad = {
            "strategies": [{
                "strategy": "File for FDA expedited designation at Phase 1 completion",
                "example": "Vertex / Kalydeco — stack FDA designations",
                "how_to_apply": "Field validation in a disease-relevant plant model",
            }]
        }
        violations = validate_report_dict(bad, ProductArchetype.RESEARCH_TOOL_NON_CLINICAL)
        assert len(violations) > 0, (
            "validate_report_dict must flag 'disease-relevant' in a research-tool report (C-04)"
        )

    def test_research_infrastructure_also_bans_clinical_vocab(self):
        from app.services.product_archetype import ProductArchetype, get_manifest
        manifest = get_manifest(ProductArchetype.RESEARCH_INFRASTRUCTURE_SAAS)
        assert len(manifest.banned_vocabulary) > 0, (
            "RESEARCH_INFRASTRUCTURE_SAAS (used for soil sensor) must also ban clinical vocabulary"
        )
