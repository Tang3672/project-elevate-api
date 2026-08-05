"""
Part E — Typed Strategy library (spec v4 E.1, E.2).

Tests:
  E.1  Strategy dataclass — correct fields, instantiation, no missing attributes
  E.2  TYPED_STRATEGY_LIBRARY — entries, unique IDs, populated gating fields
  E.2  filter_strategies — archetype and domain gating
  E.3  render_strategy — apply_template rendered with context
  E.3  format_typed_strategies_for_report — output shape
  E.4  format_strategies_for_report (strategy_database) dispatches to typed
       library for research_tool archetypes and returns typed fields
"""

from __future__ import annotations

import pytest
from app.services.strategy_model import (
    TYPED_STRATEGY_LIBRARY,
    Strategy,
    filter_strategies,
    format_typed_strategies_for_report,
    render_strategy,
)


# ══════════════════════════════════════════════════════════════════════════════
# E.1 — Strategy dataclass
# ══════════════════════════════════════════════════════════════════════════════

class TestStrategyDataclass:

    def _make(self, **overrides) -> Strategy:
        defaults = dict(
            id="test-strategy",
            headline="Test headline",
            archetypes=["research_tool_non_clinical"],
            domains=["LIFE_SCIENCES_RESEARCH"],
            buyer_personas=["academic_pi"],
            example_company="ACME",
            example_product="Widget",
            example_evidence="ACME did something notable.",
            source_url="https://example.com",
            how_to_apply="Do this first, then that.",
            apply_template="Do this for {product_name} first, then that.",
        )
        defaults.update(overrides)
        return Strategy(**defaults)

    def test_instantiation_succeeds(self):
        s = self._make()
        assert isinstance(s, Strategy)

    def test_id_field(self):
        s = self._make(id="my-slug")
        assert s.id == "my-slug"

    def test_headline_field(self):
        s = self._make(headline="Headline text")
        assert s.headline == "Headline text"

    def test_archetypes_is_list(self):
        s = self._make(archetypes=["research_tool_non_clinical", "research_infrastructure_saas"])
        assert isinstance(s.archetypes, list)
        assert len(s.archetypes) == 2

    def test_domains_is_list(self):
        s = self._make(domains=["LIFE_SCIENCES_RESEARCH"])
        assert isinstance(s.domains, list)

    def test_buyer_personas_is_list(self):
        s = self._make(buyer_personas=["academic_pi", "core_facility_director"])
        assert isinstance(s.buyer_personas, list)
        assert "academic_pi" in s.buyer_personas

    def test_apply_template_field(self):
        s = self._make(apply_template="Apply {product_name} here.")
        assert "{product_name}" in s.apply_template

    def test_apply_template_defaults_empty_string(self):
        s = Strategy(
            id="minimal",
            headline="HL",
            archetypes=[],
            domains=[],
            buyer_personas=[],
            example_company="Co",
            example_product="Prod",
            example_evidence="Evidence",
            source_url="https://example.com",
            how_to_apply="Apply it.",
        )
        assert s.apply_template == ""

    def test_category_field(self):
        s = self._make(category="SBIR")
        assert s.category == "SBIR"


# ══════════════════════════════════════════════════════════════════════════════
# E.2 — TYPED_STRATEGY_LIBRARY
# ══════════════════════════════════════════════════════════════════════════════

class TestTypedStrategyLibrary:

    def test_library_non_empty(self):
        assert len(TYPED_STRATEGY_LIBRARY) >= 4, (
            "TYPED_STRATEGY_LIBRARY must contain at least 4 strategies"
        )

    def test_all_entries_are_strategy_instances(self):
        for s in TYPED_STRATEGY_LIBRARY:
            assert isinstance(s, Strategy), (
                f"TYPED_STRATEGY_LIBRARY entry {s!r} is not a Strategy"
            )

    def test_ids_are_unique(self):
        ids = [s.id for s in TYPED_STRATEGY_LIBRARY]
        assert len(ids) == len(set(ids)), "Strategy IDs must be unique"

    def test_all_have_non_empty_headline(self):
        for s in TYPED_STRATEGY_LIBRARY:
            assert s.headline, f"Strategy {s.id!r} has empty headline"

    def test_all_have_non_empty_example_evidence(self):
        for s in TYPED_STRATEGY_LIBRARY:
            assert s.example_evidence, f"Strategy {s.id!r} has empty example_evidence"

    def test_all_have_source_url(self):
        for s in TYPED_STRATEGY_LIBRARY:
            assert s.source_url, f"Strategy {s.id!r} has no source_url"
            assert s.source_url.startswith("http"), (
                f"Strategy {s.id!r} source_url must be an HTTP URL"
            )

    def test_research_tool_non_clinical_strategies_exist(self):
        rt_strategies = [s for s in TYPED_STRATEGY_LIBRARY if "research_tool_non_clinical" in s.archetypes]
        assert len(rt_strategies) >= 2, (
            "Must have at least 2 strategies for research_tool_non_clinical"
        )

    def test_research_infrastructure_strategies_exist(self):
        ri_strategies = [s for s in TYPED_STRATEGY_LIBRARY if "research_infrastructure_saas" in s.archetypes]
        assert len(ri_strategies) >= 1, (
            "Must have at least 1 strategy for research_infrastructure_saas"
        )

    def test_all_typed_strategies_have_archetypes_or_domains(self):
        for s in TYPED_STRATEGY_LIBRARY:
            assert s.archetypes or s.domains, (
                f"Strategy {s.id!r} must gate on at least one archetype or domain"
            )

    def test_apply_templates_contain_placeholder(self):
        strategies_with_template = [s for s in TYPED_STRATEGY_LIBRARY if s.apply_template]
        assert strategies_with_template, "At least one strategy must have an apply_template"
        for s in strategies_with_template:
            assert "{" in s.apply_template, (
                f"Strategy {s.id!r} apply_template must contain at least one {{placeholder}}"
            )

    def test_product_name_placeholder_in_research_tool_templates(self):
        rt_strategies = [
            s for s in TYPED_STRATEGY_LIBRARY
            if "research_tool_non_clinical" in s.archetypes and s.apply_template
        ]
        assert rt_strategies, "research_tool strategies with apply_template must exist"
        for s in rt_strategies:
            assert "{product_name}" in s.apply_template, (
                f"Strategy {s.id!r} apply_template must include {{product_name}} placeholder"
            )


# ══════════════════════════════════════════════════════════════════════════════
# E.2 — filter_strategies
# ══════════════════════════════════════════════════════════════════════════════

class TestFilterStrategies:

    def test_returns_list(self):
        result = filter_strategies("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH")
        assert isinstance(result, list)

    def test_research_tool_non_clinical_returns_strategies(self):
        result = filter_strategies("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH")
        assert len(result) >= 1, "Must return at least 1 strategy for research_tool_non_clinical"

    def test_research_infrastructure_saas_returns_strategies(self):
        result = filter_strategies("research_infrastructure_saas", "LIFE_SCIENCES_RESEARCH")
        assert len(result) >= 1, "Must return at least 1 strategy for research_infrastructure_saas"

    def test_max_strategies_cap_respected(self):
        result = filter_strategies("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH", max_strategies=2)
        assert len(result) <= 2

    def test_archetype_gate_filters_correctly(self):
        result = filter_strategies("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH")
        for s in result:
            if s.archetypes:
                assert "research_tool_non_clinical" in s.archetypes, (
                    f"Strategy {s.id!r} passed archetype gate but archetypes={s.archetypes!r}"
                )

    def test_domain_gate_filters_correctly(self):
        result = filter_strategies("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH")
        for s in result:
            if s.domains:
                assert "LIFE_SCIENCES_RESEARCH" in s.domains, (
                    f"Strategy {s.id!r} passed domain gate but domains={s.domains!r}"
                )

    def test_unknown_archetype_returns_empty(self):
        result = filter_strategies("unknown_archetype_xyz", "UNKNOWN_DOMAIN")
        assert result == [], (
            "Unknown archetype/domain must return empty list, not universal fallback"
        )

    def test_empty_archetype_and_domain_returns_all_matching(self):
        result_full = filter_strategies("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH", max_strategies=100)
        result_cap4 = filter_strategies("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH", max_strategies=4)
        assert len(result_cap4) <= 4
        assert len(result_full) >= len(result_cap4)

    def test_buyer_persona_soft_filter(self):
        all_result = filter_strategies("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH", max_strategies=100)
        persona_result = filter_strategies(
            "research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH",
            buyer_persona="academic_pi", max_strategies=100,
        )
        # Persona filter should never return MORE than the unfiltered set
        assert len(persona_result) <= len(all_result)
        # And should return at least 1 (never empties the list entirely)
        assert len(persona_result) >= 1

    def test_research_infrastructure_strategies_have_correct_archetype(self):
        result = filter_strategies("research_infrastructure_saas", "LIFE_SCIENCES_RESEARCH")
        for s in result:
            if s.archetypes:
                assert "research_infrastructure_saas" in s.archetypes, (
                    f"Strategy {s.id!r} returned for research_infrastructure_saas but "
                    f"archetypes={s.archetypes!r}"
                )


# ══════════════════════════════════════════════════════════════════════════════
# E.3 — render_strategy
# ══════════════════════════════════════════════════════════════════════════════

class TestRenderStrategy:

    def _get_rt_strategy(self) -> Strategy:
        strategies = filter_strategies("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH")
        return strategies[0]

    def test_returns_dict(self):
        s = self._get_rt_strategy()
        result = render_strategy(s, {})
        assert isinstance(result, dict)

    def test_required_keys_present(self):
        s = self._get_rt_strategy()
        result = render_strategy(s, {})
        required_keys = {"id", "strategy", "example", "what_they_did", "how_to_apply", "source_url"}
        missing = required_keys - result.keys()
        assert not missing, f"render_strategy output missing keys: {missing!r}"

    def test_typed_keys_present(self):
        s = self._get_rt_strategy()
        result = render_strategy(s, {})
        typed_keys = {"archetypes", "domains", "buyer_personas"}
        missing = typed_keys - result.keys()
        assert not missing, f"render_strategy output missing typed keys: {missing!r}"

    def test_product_name_substituted_in_how_to_apply(self):
        strategies = [s for s in TYPED_STRATEGY_LIBRARY if "{product_name}" in s.apply_template]
        assert strategies, "Need at least one strategy with {product_name} template"
        s = strategies[0]
        result = render_strategy(s, {"product_name": "Hublink"})
        assert "Hublink" in result["how_to_apply"], (
            "render_strategy must substitute {product_name} in how_to_apply"
        )

    def test_buyer_type_substituted(self):
        strategies = [s for s in TYPED_STRATEGY_LIBRARY if "{buyer_type}" in s.apply_template]
        if not strategies:
            pytest.skip("No strategy with {buyer_type} placeholder in test library")
        s = strategies[0]
        result = render_strategy(s, {"buyer_type": "academic PI"})
        assert "academic PI" in result["how_to_apply"]

    def test_missing_placeholder_not_raised(self):
        s = self._get_rt_strategy()
        # Must not raise KeyError even with empty context
        result = render_strategy(s, {})
        assert isinstance(result["how_to_apply"], str)
        assert len(result["how_to_apply"]) > 0

    def test_missing_placeholder_left_visible(self):
        strategies = [s for s in TYPED_STRATEGY_LIBRARY if "{product_name}" in s.apply_template]
        assert strategies
        s = strategies[0]
        result = render_strategy(s, {})
        # Missing placeholder should stay visible, not become empty string or crash
        assert "{product_name}" in result["how_to_apply"], (
            "Unfilled placeholders must remain visible (SafeDict behavior)"
        )

    def test_example_combines_company_and_product(self):
        s = self._get_rt_strategy()
        result = render_strategy(s, {})
        assert s.example_company in result["example"]
        assert s.example_product in result["example"]

    def test_strategy_field_is_headline(self):
        s = self._get_rt_strategy()
        result = render_strategy(s, {})
        assert result["strategy"] == s.headline

    def test_strategy_without_template_falls_back_to_how_to_apply(self):
        s = Strategy(
            id="no-template",
            headline="No template strategy",
            archetypes=["research_tool_non_clinical"],
            domains=["LIFE_SCIENCES_RESEARCH"],
            buyer_personas=[],
            example_company="Co",
            example_product="Prod",
            example_evidence="Evidence.",
            source_url="https://example.com",
            how_to_apply="Apply it this way.",
            apply_template="",  # no template
        )
        result = render_strategy(s, {"product_name": "Hublink"})
        assert result["how_to_apply"] == "Apply it this way."


# ══════════════════════════════════════════════════════════════════════════════
# E.3 — format_typed_strategies_for_report
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatTypedStrategiesForReport:

    def test_returns_list(self):
        result = format_typed_strategies_for_report("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH")
        assert isinstance(result, list)

    def test_non_empty_for_research_tool(self):
        result = format_typed_strategies_for_report("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH")
        assert len(result) >= 1

    def test_each_entry_has_required_keys(self):
        result = format_typed_strategies_for_report("research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH")
        required = {"id", "strategy", "example", "what_they_did", "how_to_apply", "source_url"}
        for entry in result:
            missing = required - entry.keys()
            assert not missing, f"Entry missing keys: {missing!r}"

    def test_context_substituted(self):
        result = format_typed_strategies_for_report(
            "research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH",
            context={"product_name": "Hublink"},
        )
        text = " ".join(e["how_to_apply"] for e in result)
        assert "Hublink" in text, (
            "format_typed_strategies_for_report must substitute context placeholders"
        )

    def test_max_strategies_respected(self):
        result = format_typed_strategies_for_report(
            "research_tool_non_clinical", "LIFE_SCIENCES_RESEARCH", max_strategies=2
        )
        assert len(result) <= 2

    def test_empty_for_unknown_archetype(self):
        result = format_typed_strategies_for_report("totally_unknown", "UNKNOWN_DOMAIN")
        assert result == []


# ══════════════════════════════════════════════════════════════════════════════
# E.4 — format_strategies_for_report dispatches to typed library for research_tool
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatStrategiesDispatch:
    """
    format_strategies_for_report in strategy_database.py must route research_tool
    and research_infrastructure archetypes through the typed library so the typed
    gating fields (id, archetypes, domains, buyer_personas) appear in output.
    """

    def _strategies(self, sub_id: str) -> list:
        from app.services.strategy_database import format_strategies_for_report
        return format_strategies_for_report(sub_id)

    def test_research_tool_output_has_id_field(self):
        strategies = self._strategies("research_tool_non_clinical")
        assert strategies, "Must return at least one strategy"
        for s in strategies:
            assert "id" in s, (
                "format_strategies_for_report must include 'id' field for research_tool "
                "archetypes (dispatched from typed library)"
            )

    def test_research_tool_output_has_archetypes_field(self):
        strategies = self._strategies("research_tool_non_clinical")
        for s in strategies:
            assert "archetypes" in s, (
                "format_strategies_for_report must include 'archetypes' field for research_tool"
            )
            assert isinstance(s["archetypes"], list)

    def test_research_tool_output_has_domains_field(self):
        strategies = self._strategies("research_tool_non_clinical")
        for s in strategies:
            assert "domains" in s, (
                "format_strategies_for_report must include 'domains' field for research_tool"
            )

    def test_research_tool_output_has_buyer_personas_field(self):
        strategies = self._strategies("research_tool_non_clinical")
        for s in strategies:
            assert "buyer_personas" in s, (
                "format_strategies_for_report must include 'buyer_personas' field for research_tool"
            )

    def test_research_infrastructure_output_has_typed_fields(self):
        strategies = self._strategies("research_infrastructure_saas")
        assert strategies
        for s in strategies:
            assert "id" in s
            assert "archetypes" in s
            assert "domains" in s

    def test_clinical_archetypes_still_return_correct_format(self):
        strategies = self._strategies("drug_amr")
        assert strategies, "drug_amr must still return strategies"
        for s in strategies:
            for key in ("strategy", "example", "what_they_did", "how_to_apply", "source_url"):
                assert key in s, f"drug_amr strategy missing key {key!r}"

    def test_research_tool_ids_are_non_empty_strings(self):
        strategies = self._strategies("research_tool_non_clinical")
        for s in strategies:
            assert isinstance(s["id"], str) and s["id"], (
                "Strategy id must be a non-empty string"
            )

    def test_research_tool_how_to_apply_is_non_empty(self):
        strategies = self._strategies("research_tool_non_clinical")
        for s in strategies:
            assert s.get("how_to_apply"), (
                "how_to_apply must be non-empty (template or fallback)"
            )
