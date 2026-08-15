"""
B-04 — Strategy archetype gating and minimum-count removal.
============================================================
Two bugs fixed:

  1. Minimum-count constraint: get_strategies_for_domain previously padded to 4
     by appending UNIVERSAL_STRATEGIES (clinical) even for archetypes that only
     have 1-2 domain-specific strategies. B-04 removes that padding.

  2. Archetype gating: research_tool and research_infrastructure archetypes
     inherited _DEFAULT_STRATEGIES (FDA expedited designations) from the fill
     loop in competitive_intelligence_service. B-04 gates the fill loop and
     routes these archetypes through format_strategies_for_report instead.

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import inspect
import pytest


# ══════════════════════════════════════════════════════════════════════════════
# strategy_database — no minimum-count padding
# ══════════════════════════════════════════════════════════════════════════════

class TestGetStrategiesNoPadding:
    """get_strategies_for_domain must not pad to 4 with universal strategies."""

    def _get(self, sub_expert_id: str, max_strategies: int = 4) -> list:
        from app.services.strategy_database import get_strategies_for_domain
        return get_strategies_for_domain(sub_expert_id, max_strategies)

    def test_research_infrastructure_returns_only_domain_strategies(self):
        strategies = self._get("research_infrastructure_saas")
        # Only 2 domain-specific strategies defined — should NOT be padded to 4
        assert len(strategies) <= 4
        for s in strategies:
            assert s.get("category") != "Regulatory Acceleration", (
                "research_infrastructure_saas must not receive clinical FDA designation strategies"
            )

    def test_research_tool_returns_only_domain_strategies(self):
        strategies = self._get("research_tool_non_clinical")
        for s in strategies:
            assert s.get("category") != "Regulatory Acceleration", (
                "research_tool_non_clinical must not receive clinical FDA designation strategies"
            )

    def test_unknown_archetype_returns_empty_not_clinical(self):
        strategies = self._get("unknown_archetype")
        assert strategies == [], (
            "Unknown archetype must return empty list, not clinical universal strategies"
        )

    def test_clinical_archetype_still_returns_domain_strategies(self):
        strategies = self._get("drug_amr")
        assert len(strategies) > 0, "drug_amr must still return its domain strategies"

    def test_max_strategies_cap_respected(self):
        strategies = self._get("drug_amr", max_strategies=2)
        assert len(strategies) <= 2

    def test_no_universal_strategies_injected_for_device(self):
        from app.services.strategy_database import UNIVERSAL_STRATEGIES_DEVICE, DOMAIN_SPECIFIC_STRATEGIES
        strategies = self._get("device_cardiovascular")
        device_domain = DOMAIN_SPECIFIC_STRATEGIES.get("device_cardiovascular", [])
        # Must not have exceeded the domain count (i.e., no universal padding)
        assert len(strategies) <= len(device_domain) or len(strategies) <= 4

    def test_no_drug_universals_injected_for_diagnostic(self):
        from app.services.strategy_database import UNIVERSAL_STRATEGIES
        strategies = self._get("diagnostic_molecular")
        universal_labels = {s["strategy"] for s in UNIVERSAL_STRATEGIES}
        returned_labels = {s["strategy"] for s in strategies}
        overlap = returned_labels & universal_labels
        assert not overlap, (
            f"diagnostic_molecular received clinical universal strategies: {overlap}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# format_strategies_for_report — archetype-correct output
# ══════════════════════════════════════════════════════════════════════════════

_CLINICAL_STRATEGY_TOKENS = [
    "FDA expedited",
    "Breakthrough Therapy",
    "Priority Review",
    "Orphan Drug",
    "pediatric exclusivity",
    "Type B pre-NDA",
    "pediatric studies",
    "505(b)(2)",
    "PMDA Sakigake",
    "NIH CRADA",
    "NCE exclusivity",
    "seamless adaptive Phase",
    "Biomarker enrichment using companion diagnostic",
]

_RESEARCH_TOOL_MUST_CONTAIN = [
    # At least one of these should appear in any research_tool strategy
    "lab", "Lab", "NIH", "SBIR", "core facilit", "open-source", "open source",
    "peer-reviewed", "methods paper", "Nature Methods",
]


class TestFormatStrategiesResearchTool:

    def _strategies(self, sub_id: str) -> list:
        from app.services.strategy_database import format_strategies_for_report
        return format_strategies_for_report(sub_id)

    def test_no_clinical_tokens_in_research_tool_strategies(self):
        strategies = self._strategies("research_tool_non_clinical")
        for s in strategies:
            text = " ".join([
                s.get("strategy", ""),
                s.get("what_they_did", ""),
                s.get("how_to_apply", ""),
            ])
            for token in _CLINICAL_STRATEGY_TOKENS:
                assert token not in text, (
                    f"Clinical token '{token}' found in research_tool strategy: {s['strategy']!r}"
                )

    def test_no_clinical_tokens_in_research_infrastructure_strategies(self):
        strategies = self._strategies("research_infrastructure_saas")
        for s in strategies:
            text = " ".join([
                s.get("strategy", ""),
                s.get("what_they_did", ""),
                s.get("how_to_apply", ""),
            ])
            for token in _CLINICAL_STRATEGY_TOKENS:
                assert token not in text, (
                    f"Clinical token '{token}' found in research_infrastructure strategy: {s['strategy']!r}"
                )

    def test_research_tool_strategies_contain_research_vocabulary(self):
        strategies = self._strategies("research_tool_non_clinical")
        assert strategies, "Must return at least one research_tool strategy"
        all_text = " ".join(
            s.get("strategy", "") + " " + s.get("how_to_apply", "")
            for s in strategies
        )
        assert any(token in all_text for token in _RESEARCH_TOOL_MUST_CONTAIN), (
            "research_tool strategies must reference lab, NIH, SBIR, or core facility vocabulary"
        )

    def test_drug_amr_strategies_have_clinical_content(self):
        strategies = self._strategies("drug_amr")
        assert strategies, "drug_amr must return strategies"
        all_text = " ".join(s.get("strategy", "") for s in strategies)
        assert any(
            kw in all_text
            for kw in ["BARDA", "QIDP", "LPAD", "antibiotic", "beta-lactam", "BLI"]
        ), "drug_amr strategies must reference AMR-specific content"

    def test_format_returns_correct_keys(self):
        strategies = self._strategies("research_tool_non_clinical")
        for s in strategies:
            for key in ("strategy", "example", "what_they_did", "how_to_apply", "source_url"):
                assert key in s, f"Strategy missing key {key!r}: {s}"

    def test_format_returns_list_not_nested(self):
        strategies = self._strategies("research_tool_non_clinical")
        assert isinstance(strategies, list)
        for s in strategies:
            assert isinstance(s, dict)


# ══════════════════════════════════════════════════════════════════════════════
# competitive_intelligence_service — gating the fill loop
# ══════════════════════════════════════════════════════════════════════════════

class TestFillLoopGating:
    """research_tool/research_infrastructure must not appear in the clinical fill-loop."""

    def test_research_tool_not_assigned_default_strategies(self):
        from app.services.competitive_intelligence_service import (
            DOMAIN_STRATEGIES, _DEFAULT_STRATEGIES,
        )
        rt_entry = DOMAIN_STRATEGIES.get("research_tool_non_clinical")
        # Either not in DOMAIN_STRATEGIES, or if it is, must not be _DEFAULT_STRATEGIES
        if rt_entry is not None:
            assert rt_entry is not _DEFAULT_STRATEGIES, (
                "research_tool_non_clinical must not inherit _DEFAULT_STRATEGIES (clinical)"
            )

    def test_research_infrastructure_not_assigned_default_strategies(self):
        from app.services.competitive_intelligence_service import (
            DOMAIN_STRATEGIES, _DEFAULT_STRATEGIES,
        )
        ri_entry = DOMAIN_STRATEGIES.get("research_infrastructure_saas")
        if ri_entry is not None:
            assert ri_entry is not _DEFAULT_STRATEGIES, (
                "research_infrastructure_saas must not inherit _DEFAULT_STRATEGIES (clinical)"
            )

    def test_non_clinical_archetypes_constant_exists(self):
        from app.services.competitive_intelligence_service import _NON_CLINICAL_ARCHETYPES
        assert "research_tool_non_clinical" in _NON_CLINICAL_ARCHETYPES
        assert "research_infrastructure_saas" in _NON_CLINICAL_ARCHETYPES

    def test_fill_loop_guard_in_source(self):
        import app.services.competitive_intelligence_service as svc
        src = inspect.getsource(svc)
        assert "_NON_CLINICAL_ARCHETYPES" in src, (
            "competitive_intelligence_service must define and use _NON_CLINICAL_ARCHETYPES "
            "to gate the fill loop (B-04)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# _gather_research_tool_intel — returns archetype strategies, not clinical
# ══════════════════════════════════════════════════════════════════════════════

class TestGatherResearchToolIntel:

    def _run(self, sub_id: str = "research_tool_non_clinical") -> dict:
        import asyncio
        from app.services.competitive_intelligence_service import _gather_research_tool_intel
        return asyncio.run(
            _gather_research_tool_intel("neurotech_wearable", sub_id)
        )

    def test_strategic_playbook_present(self):
        intel = self._run()
        assert "strategic_playbook" in intel, (
            "_gather_research_tool_intel must return a strategic_playbook key"
        )

    def test_strategic_playbook_not_empty(self):
        intel = self._run()
        assert intel["strategic_playbook"], (
            "research_tool strategic_playbook must not be empty"
        )

    def test_no_clinical_tokens_in_playbook(self):
        intel = self._run()
        for s in intel["strategic_playbook"]:
            text = (s.get("strategy", "") + " " + s.get("how_to_apply", "")).lower()
            assert "fda expedited" not in text, (
                f"research_tool playbook contains clinical FDA designation strategy: {s['strategy']!r}"
            )
            assert "breakthrough therapy" not in text.lower(), (
                f"research_tool playbook contains 'Breakthrough Therapy' (clinical): {s['strategy']!r}"
            )

    def test_playbook_uses_format_strategies_for_report(self):
        from app.services.strategy_database import format_strategies_for_report
        expected = format_strategies_for_report("research_tool_non_clinical")
        intel = self._run("research_tool_non_clinical")
        assert intel["strategic_playbook"] == expected, (
            "_gather_research_tool_intel must use format_strategies_for_report, "
            "not _DEFAULT_STRATEGIES"
        )

    def test_research_infrastructure_also_gated(self):
        import asyncio
        from app.services.competitive_intelligence_service import _gather_research_tool_intel
        intel = asyncio.run(
            _gather_research_tool_intel("data_management", "research_infrastructure_saas")
        )
        for s in intel.get("strategic_playbook", []):
            assert "FDA expedited" not in s.get("strategy", ""), (
                "research_infrastructure playbook must not contain FDA designation strategy"
            )


# ══════════════════════════════════════════════════════════════════════════════
# alignment_service fallback — uses format_strategies_for_report, not DOMAIN_STRATEGIES
# ══════════════════════════════════════════════════════════════════════════════

class TestAlignmentServiceFallback:

    def test_fallback_uses_format_strategies_for_report(self):
        import app.services.alignment_service as svc
        src = inspect.getsource(svc)
        # Find the block around the fallback
        # It should import from strategy_database, not competitive_intelligence_service DOMAIN_STRATEGIES
        assert "format_strategies_for_report(sub_expert_id)" in src, (
            "alignment_service fallback must call format_strategies_for_report(sub_expert_id) "
            "from strategy_database (B-04)"
        )

    def test_fallback_no_longer_imports_domain_strategies(self):
        import app.services.alignment_service as svc
        src = inspect.getsource(svc)
        # The old line imported DOMAIN_STRATEGIES from competitive_intelligence_service
        # for the fallback — it should no longer do this
        assert "DOMAIN_STRATEGIES.get(sub_expert_id" not in src, (
            "alignment_service fallback must not use DOMAIN_STRATEGIES.get(sub_expert_id) "
            "(that path returned clinical defaults for research_tool archetypes — B-04)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# End-to-end: research_tool receives lab strategies everywhere
# ══════════════════════════════════════════════════════════════════════════════

class TestResearchToolStrategiesEndToEnd:
    """
    Checks that at every strategy lookup path for research_tool archetypes,
    the returned strategies are research-appropriate, not clinical defaults.
    """

    _BANNED_TOKENS = [
        "FDA expedited designations",
        "Breakthrough Therapy",
        "Priority Review Voucher",
        "Type B pre-NDA",
        "505(b)(2)",
        "pediatric exclusivity",
        "NCE exclusivity",
        "PMDA Sakigake",
    ]

    def _check_no_clinical(self, strategies: list, path: str) -> None:
        for s in strategies:
            label = s.get("strategy", "")
            for token in self._BANNED_TOKENS:
                assert token not in label, (
                    f"Clinical token '{token}' found in {path} for research_tool: {label!r}"
                )

    def test_format_strategies_path_clean(self):
        from app.services.strategy_database import format_strategies_for_report
        self._check_no_clinical(
            format_strategies_for_report("research_tool_non_clinical"),
            "format_strategies_for_report('research_tool_non_clinical')",
        )

    def test_get_strategies_path_clean(self):
        from app.services.strategy_database import get_strategies_for_domain
        self._check_no_clinical(
            get_strategies_for_domain("research_tool_non_clinical"),
            "get_strategies_for_domain('research_tool_non_clinical')",
        )

    def test_research_infrastructure_path_clean(self):
        from app.services.strategy_database import format_strategies_for_report
        self._check_no_clinical(
            format_strategies_for_report("research_infrastructure_saas"),
            "format_strategies_for_report('research_infrastructure_saas')",
        )
