"""
B-05 part 2 — competitor_schema normalization layer.
=====================================================
Covers the new competitor_schema.py module (normalize_competitor,
normalize_landscape) and the enriched _RESEARCH_TOOL_COMPARATORS entries
that now carry B-05 fields (overlap, where_you_win, where_you_lose,
switching_cost, price_point, controlled-vocab category).

Companion to test_b05_competitor_schema.py, which covers the
get_competitor_schema / validate_competitor_entry API.
"""

from __future__ import annotations

import pytest

# ══════════════════════════════════════════════════════════════════════════════
# normalize_competitor — null-safety and defaults
# ══════════════════════════════════════════════════════════════════════════════


class TestNormalizeCompetitor:

    def _norm(self, raw: dict) -> dict:
        from app.services.competitor_schema import normalize_competitor
        return normalize_competitor(raw)

    def test_all_field_defaults_present_from_empty_dict(self):
        from app.services.competitor_schema import _FIELD_DEFAULTS
        out = self._norm({})
        for key in _FIELD_DEFAULTS:
            assert key in out, f"normalize_competitor must add default for {key!r}"

    def test_provided_values_not_overwritten(self):
        out = self._norm({"name": "ActiGraph", "overlap": "motion logging"})
        assert out["name"] == "ActiGraph"
        assert out["overlap"] == "motion logging"

    def test_none_value_replaced_by_default(self):
        out = self._norm({"name": "X", "overlap": None})
        assert out["overlap"] == ""

    def test_incumbent_truthy_int_coerced_to_bool_true(self):
        assert self._norm({"incumbent": 1})["incumbent"] is True

    def test_incumbent_zero_coerced_to_bool_false(self):
        assert self._norm({"incumbent": 0})["incumbent"] is False

    def test_incumbent_absent_defaults_false(self):
        assert self._norm({})["incumbent"] is False

    def test_advantages_string_coerced_to_list(self):
        out = self._norm({"advantages": "Fast"})
        assert isinstance(out["advantages"], list)
        assert "Fast" in out["advantages"]

    def test_vulnerabilities_string_coerced_to_list(self):
        out = self._norm({"vulnerabilities": "IV only"})
        assert isinstance(out["vulnerabilities"], list)

    def test_advantages_absent_defaults_empty_list(self):
        assert self._norm({})["advantages"] == []

    def test_vulnerabilities_absent_defaults_empty_list(self):
        assert self._norm({})["vulnerabilities"] == []

    def test_stage_present_as_empty_string_for_research_tool(self):
        out = self._norm({"name": "Tool", "category": "direct"})
        assert out.get("stage") == ""

    def test_company_present_as_empty_string_for_research_tool(self):
        out = self._norm({"name": "Tool"})
        assert out.get("company") == ""

    def test_no_none_values_in_output(self):
        raw = {
            "name": "X", "overlap": None, "where_you_win": None,
            "where_you_lose": None, "switching_cost": None, "price_point": None,
        }
        out = self._norm(raw)
        # price_point defaults to None but every other string field should be ""
        for k, v in out.items():
            if k != "price_point":
                assert v is not None, f"Field {k!r} must not be None after normalization"

    def test_returned_dict_is_a_copy(self):
        raw = {"name": "A"}
        out = self._norm(raw)
        out["name"] = "mutated"
        assert raw["name"] == "A"


# ══════════════════════════════════════════════════════════════════════════════
# normalize_landscape — key unification and entry normalization
# ══════════════════════════════════════════════════════════════════════════════


class TestNormalizeLandscape:

    def _nl(self, landscape: dict) -> dict:
        from app.services.competitor_schema import normalize_landscape
        return normalize_landscape(landscape)

    def test_competitors_key_preserved(self):
        out = self._nl({"competitors": [{"name": "A"}]})
        assert "competitors" in out
        assert out["competitors"][0]["name"] == "A"

    def test_research_tool_comparators_aliased_to_competitors(self):
        out = self._nl({"research_tool_comparators": [{"name": "B"}]})
        assert out["competitors"][0]["name"] == "B"
        assert "research_tool_comparators" not in out

    def test_comparators_aliased_to_competitors(self):
        out = self._nl({"comparators": [{"name": "C"}]})
        assert out["competitors"][0]["name"] == "C"
        assert "comparators" not in out

    def test_empty_landscape_has_empty_competitors(self):
        out = self._nl({})
        assert out.get("competitors") == []

    def test_all_competitor_entries_normalized(self):
        from app.services.competitor_schema import _FIELD_DEFAULTS
        out = self._nl({"competitors": [{}, {}]})
        for c in out["competitors"]:
            for key in _FIELD_DEFAULTS:
                assert key in c, f"Normalized entry missing {key!r}"

    def test_original_dict_not_mutated(self):
        original = {"competitors": [{"name": "A"}]}
        self._nl(original)
        assert "stage" not in original["competitors"][0]

    def test_extra_landscape_fields_preserved(self):
        out = self._nl({"corpus": "research_tool_functional", "competitors": []})
        assert out.get("corpus") == "research_tool_functional"

    def test_competitors_key_takes_precedence_over_aliases(self):
        out = self._nl({
            "competitors": [{"name": "primary"}],
            "comparators": [{"name": "alias"}],
        })
        names = [c["name"] for c in out["competitors"]]
        assert "primary" in names
        assert "alias" not in names


# ══════════════════════════════════════════════════════════════════════════════
# COMPETITOR_CATEGORY controlled vocabulary
# ══════════════════════════════════════════════════════════════════════════════


class TestCompetitorCategory:

    def test_status_quo_in_vocab(self):
        from app.services.competitor_schema import COMPETITOR_CATEGORY
        assert "status_quo" in COMPETITOR_CATEGORY

    def test_direct_in_vocab(self):
        from app.services.competitor_schema import COMPETITOR_CATEGORY
        assert "direct" in COMPETITOR_CATEGORY

    def test_adjacent_general_in_vocab(self):
        from app.services.competitor_schema import COMPETITOR_CATEGORY
        assert "adjacent_general" in COMPETITOR_CATEGORY

    def test_upstream_platform_in_vocab(self):
        from app.services.competitor_schema import COMPETITOR_CATEGORY
        assert "upstream_platform" in COMPETITOR_CATEGORY

    def test_drug_categories_in_vocab(self):
        from app.services.competitor_schema import COMPETITOR_CATEGORY
        for cat in ("approved_drug", "pipeline_drug"):
            assert cat in COMPETITOR_CATEGORY

    def test_is_frozenset(self):
        from app.services.competitor_schema import COMPETITOR_CATEGORY
        assert isinstance(COMPETITOR_CATEGORY, frozenset)


# F-2: TestResearchToolComparatorsB05Fields deleted — the static _RESEARCH_TOOL_COMPARATORS
# list was Hublink-specific and has been replaced by _extract_research_tool_comparators().
# Schema compliance is enforced at normalisation time by normalize_landscape().


# ══════════════════════════════════════════════════════════════════════════════
# alignment_service wiring — normalize_landscape is called
# ══════════════════════════════════════════════════════════════════════════════


class TestAlignmentServiceNormalizationWiring:

    def test_normalize_landscape_called_in_attach(self):
        import inspect
        import app.services.alignment_service as svc
        src = inspect.getsource(svc.attach_competitive_landscape)
        assert "normalize_landscape" in src, (
            "attach_competitive_landscape must call normalize_landscape (B-05)"
        )

    def test_normalize_landscape_called_for_drug_path(self):
        import inspect
        import app.services.alignment_service as svc
        src = inspect.getsource(svc.attach_competitive_landscape)
        # Both the research_tool path and the drug path must call normalize_landscape
        assert src.count("normalize_landscape") >= 2, (
            "Both the research_tool and drug paths in attach_competitive_landscape "
            "must call normalize_landscape"
        )


# ══════════════════════════════════════════════════════════════════════════════
# pdf_renderer — corpus-aware rendering, no "undefined"
# ══════════════════════════════════════════════════════════════════════════════


import re as _re

def _strip_tags(html: str) -> str:
    return _re.sub(r"<[^>]+>", " ", html)


class TestRendererNormalization:

    def _render(self, ci: dict) -> str:
        from app.services.pdf_renderer import _render_competitive_landscape
        return _render_competitive_landscape(ci)

    def test_research_tool_renders_overlap_column(self):
        ci = {
            "corpus": "research_tool_functional",
            "competitors": [{
                "name": "ActiGraph", "category": "direct",
                "description": "Motion logger", "incumbent": True,
                "overlap": "wearable data logging",
                "where_you_win": "open format",
                "where_you_lose": "brand recognition",
                "switching_cost": "High",
                "price_point": "$500",
            }],
        }
        html = self._render(ci)
        assert "Overlap" in html or "wearable data logging" in html

    def test_research_tool_renders_win_lose_columns(self):
        ci = {
            "corpus": "research_tool_functional",
            "competitors": [{
                "name": "A", "category": "direct", "description": "Tool",
                "overlap": "sync", "where_you_win": "cost",
                "where_you_lose": "brand", "switching_cost": "Medium",
                "price_point": "$0",
            }],
        }
        html = self._render(ci)
        assert "Where You Win" in html or "cost" in html
        assert "Where You Lose" in html or "brand" in html

    def test_research_tool_no_undefined(self):
        ci = {
            "corpus": "research_tool_functional",
            "competitors": [
                {"name": "A", "category": "direct", "description": "d"},
            ],
        }
        html = self._render(ci)
        assert "undefined" not in _strip_tags(html).lower()

    def test_drug_no_undefined(self):
        ci = {
            "competitors": [
                {
                    "name": "Vancomycin", "company": "Pfizer", "stage": "approved",
                    "brand_name": "Vancocin", "route": "IV",
                    "advantages": ["Gold standard"],
                    "vulnerabilities": ["nephrotoxicity"],
                },
            ],
        }
        html = self._render(ci)
        assert "undefined" not in _strip_tags(html).lower()

    def test_empty_competitors_returns_empty_section(self):
        html = self._render({"corpus": "research_tool_functional", "competitors": []})
        # No table rows should appear, but section wrapper may still be present
        assert "undefined" not in _strip_tags(html).lower()

    def test_none_ci_returns_empty_string(self):
        assert self._render(None) == ""

    def test_empty_ci_returns_empty_string(self):
        assert self._render({}) == ""

    def test_research_tool_comparators_key_alias_resolved(self):
        ci = {
            "research_tool_comparators": [{
                "name": "Via alias", "category": "direct", "description": "d",
                "overlap": "logging", "where_you_win": "w", "where_you_lose": "l",
                "switching_cost": "Low", "price_point": "$0",
            }],
        }
        html = self._render(ci)
        assert "Via alias" in html

    def test_drug_competitor_with_none_company_no_undefined(self):
        ci = {
            "competitors": [{"name": "X", "company": None, "stage": None}],
        }
        html = self._render(ci)
        assert "undefined" not in _strip_tags(html).lower()
        assert "None" not in _strip_tags(html)

    def test_normalize_landscape_called_in_renderer(self):
        import inspect
        from app.services.pdf_renderer import _render_competitive_landscape
        src = inspect.getsource(_render_competitive_landscape)
        assert "normalize_landscape" in src, (
            "_render_competitive_landscape must call normalize_landscape (B-05)"
        )
