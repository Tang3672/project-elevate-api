"""
Part F — Research Tool intake: non-clinical product type and quick examples.
============================================================================
Items verified:
  1. "Research Tool / Lab Infrastructure" button exists in the type-grid.
  2. `research_tool_non_clinical` is in the `setEx` typeOrder array.
  3. EXAMPLES array contains at least two research_tool_non_clinical entries.
  4. Quick-example chips are present for the research tool examples.
  5. `selectType()` has a placeholder for `research_tool_non_clinical`.

All tests are pure source-inspection (no API key, no DB).
"""

from __future__ import annotations

import os
import re


def _app_html() -> str:
    path = os.path.normpath(
        os.path.join(
            os.path.dirname(__file__), "..", "..", "ProjectElevate-Frontend", "app.html"
        )
    )
    with open(path, encoding="utf-8") as f:
        return f.read()


class TestResearchToolTypeButton:

    def test_button_exists_in_type_grid(self):
        src = _app_html()
        assert "selectType('research_tool_non_clinical'" in src, (
            "Type-grid must contain a button calling selectType('research_tool_non_clinical'...)"
        )

    def test_button_has_research_tool_label(self):
        src = _app_html()
        m = re.search(
            r"selectType\('research_tool_non_clinical'.*?<span class=\"type-name\">(.*?)</span>",
            src, re.DOTALL,
        )
        assert m, "Research Tool button must have a type-name span"
        assert "research" in m.group(1).lower() or "tool" in m.group(1).lower(), (
            f"type-name must say 'Research Tool', got: {m.group(1)!r}"
        )

    def test_button_has_descriptor_text(self):
        src = _app_html()
        m = re.search(
            r"selectType\('research_tool_non_clinical'.*?<span class=\"type-desc\">(.*?)</span>",
            src, re.DOTALL,
        )
        assert m, "Research Tool button must have a type-desc span"
        desc = m.group(1).lower()
        assert any(kw in desc for kw in ("lab", "software", "instrument", "infrastructure")), (
            f"type-desc should mention lab/software/instruments/infrastructure; got: {desc!r}"
        )

    def test_type_grid_changed_to_3_columns(self):
        src = _app_html()
        assert "repeat(3,1fr)" in src, (
            "type-grid must be 3 columns to fit 9 buttons cleanly (3×3 layout)"
        )


class TestResearchToolExamples:

    def _examples_block(self) -> str:
        src = _app_html()
        m = re.search(r"const EXAMPLES\s*=\s*\[(.*?)\];", src, re.DOTALL)
        assert m, "Could not find EXAMPLES array in app.html"
        return m.group(1)

    def test_examples_array_has_research_tool_entry(self):
        block = self._examples_block()
        assert "research_tool_non_clinical" in block, (
            "EXAMPLES array must contain at least one research_tool_non_clinical entry"
        )

    def test_examples_array_has_two_research_tool_entries(self):
        block = self._examples_block()
        count = block.count("research_tool_non_clinical")
        assert count >= 2, (
            f"EXAMPLES array should have ≥2 research_tool_non_clinical entries; found {count}"
        )

    def test_research_tool_example_has_non_empty_idea(self):
        block = self._examples_block()
        m = re.search(
            r"type:'research_tool_non_clinical'.*?idea:'([^']+)'",
            block, re.DOTALL,
        )
        assert m and len(m.group(1)) > 30, (
            "research_tool_non_clinical example idea must be a substantive description"
        )

    def test_research_tool_example_has_empty_pathogen(self):
        block = self._examples_block()
        # All research tool examples should not require a pathogen
        for m in re.finditer(
            r"type:'research_tool_non_clinical'.*?pathogen:'([^']*)'",
            block, re.DOTALL,
        ):
            assert m.group(1) == "", (
                "research_tool_non_clinical examples should have empty pathogen"
            )


class TestResearchToolChips:

    def _chips_block(self) -> str:
        src = _app_html()
        m = re.search(r'<div class="chips">(.*?)</div>', src, re.DOTALL)
        assert m, "Could not find chips div in app.html"
        return m.group(1)

    def test_research_tool_chip_present(self):
        block = self._chips_block()
        # At least one chip must call setEx with an index ≥ 12 (research tool entries)
        chip_indices = [int(x) for x in re.findall(r"setEx\((\d+)\)", block)]
        assert any(i >= 12 for i in chip_indices), (
            "Chips section must include at least one research tool example (setEx index ≥ 12)"
        )

    def test_research_tool_chip_has_descriptive_label(self):
        src = _app_html()
        m = re.search(r'setEx\(12\)[^>]*>(.*?)</button>', src, re.DOTALL)
        assert m, "setEx(12) chip must exist"
        label = m.group(1).strip()
        assert len(label) > 5, f"Chip label too short: {label!r}"


class TestSelectTypePlaceholder:

    def _placeholders_block(self) -> str:
        src = _app_html()
        m = re.search(r"const placeholders\s*=\s*\{(.*?)\};", src, re.DOTALL)
        assert m, "Could not find placeholders object in selectType()"
        return m.group(1)

    def test_research_tool_placeholder_defined(self):
        block = self._placeholders_block()
        assert "research_tool_non_clinical" in block, (
            "selectType() placeholders must include research_tool_non_clinical key"
        )

    def test_research_tool_placeholder_non_empty(self):
        block = self._placeholders_block()
        m = re.search(r"research_tool_non_clinical\s*:\s*'([^']+)'", block)
        assert m and len(m.group(1)) > 20, (
            "research_tool_non_clinical placeholder must be a descriptive string"
        )


class TestSetExTypeButtonMatching:
    """setEx() now finds buttons by onclick attribute value rather than a
    hardcoded typeOrder index array — verify the mechanism works."""

    def _setex_src(self) -> str:
        src = _app_html()
        m = re.search(r"function setEx\(i\)\s*\{(.*?)\n\}", src, re.DOTALL)
        assert m, "Could not find setEx() function in app.html"
        return m.group(1)

    def test_setex_matches_by_onclick(self):
        src = self._setex_src()
        assert "getAttribute('onclick')" in src or "getAttribute(\"onclick\")" in src, (
            "setEx() must find type buttons by their onclick attribute value, "
            "not by a hardcoded typeOrder index array"
        )

    def test_research_tool_button_onclick_present(self):
        src = _app_html()
        assert "selectType('research_tool_non_clinical'" in src, (
            "A type button with selectType('research_tool_non_clinical'...) must exist "
            "so setEx() can activate it for research tool examples"
        )

    def test_research_infrastructure_button_present(self):
        src = _app_html()
        assert "selectType('research_infrastructure_saas'" in src, (
            "A type button for research_infrastructure_saas must exist in the type grid "
            "as a first-class Research domain option"
        )
