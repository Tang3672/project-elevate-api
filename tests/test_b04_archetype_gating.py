"""
B-04 — Minimum-count deletion and archetype-level strategy gating
==================================================================
Two failure modes this spec item guards against:

  1. Minimum-count padding: prompts that say "list at least N competitors /
     strategies / citations" force the LLM to invent entries when the real
     market has fewer. Correct behaviour: report what actually exists.

  2. Cross-archetype contamination: a research-tool report receiving drug or
     device strategies (e.g. "Pursue 510(k)" or "Stack FDA expedited
     designations") is equally wrong. Strategy selection must be gated by
     sub_expert_id.

These are pure-Python tests (no API key, no DB).
"""

from __future__ import annotations

import re

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# Minimum-count instructions deleted from static prompt strings
# ══════════════════════════════════════════════════════════════════════════════

# Pattern: "include/list/provide/name/cite at least N <thing>" where the thing
# is competitors, strategies, players, citations, alternatives, or papers.
_MIN_COUNT_RE = re.compile(
    r'(include|list|provide|name|identify|cite)\s+'
    r'(at\s+least|a\s+minimum\s+of)\s+\d+\s+'
    r'(competitor|strateg|player|alternat|paper|citation|source)',
    re.IGNORECASE,
)


def _scan_source(module_path: str, attr_pattern: str | None = None) -> str:
    """Return concatenated string-constant content from a module."""
    import importlib
    mod = importlib.import_module(module_path)
    parts: list[str] = []
    for name in dir(mod):
        obj = getattr(mod, name)
        if isinstance(obj, str):
            if attr_pattern is None or re.search(attr_pattern, name, re.IGNORECASE):
                parts.append(obj)
    return "\n".join(parts)


class TestNoMinimumCountInPrompts:

    def test_source_aggregator_no_minimum_count(self):
        """source_aggregator_service must not contain 'cite at least N papers'."""
        text = _scan_source("app.services.source_aggregator_service")
        m = _MIN_COUNT_RE.search(text)
        assert m is None, (
            f"Minimum-count instruction found in source_aggregator_service: {m.group()!r} — "
            "remove it; LLM should cite every relevant paper, not a count floor"
        )

    def test_alignment_service_no_minimum_count(self):
        """alignment_service prompt constants must not set minimum counts."""
        text = _scan_source("app.services.alignment_service")
        m = _MIN_COUNT_RE.search(text)
        assert m is None, (
            f"Minimum-count instruction in alignment_service: {m.group()!r}"
        )

    def test_competitive_intelligence_service_no_minimum_count(self):
        """competitive_intelligence_service prompts must not pad competitors."""
        text = _scan_source("app.services.competitive_intelligence_service")
        m = _MIN_COUNT_RE.search(text)
        assert m is None, (
            f"Minimum-count instruction in competitive_intelligence_service: {m.group()!r}"
        )

    def test_chapter_data_service_no_minimum_count(self):
        """chapter_data_service must not set competitor / strategy count floors."""
        text = _scan_source("app.services.chapter_data_service")
        m = _MIN_COUNT_RE.search(text)
        assert m is None, (
            f"Minimum-count instruction in chapter_data_service: {m.group()!r}"
        )

    def test_source_aggregator_uses_relevance_framing(self):
        """Citation instruction must use 'relevant' framing, not a numeric floor."""
        import app.services.source_aggregator_service as svc
        # Find the build_source_context function text
        import inspect
        src = inspect.getsource(svc)
        assert "relevant" in src.lower(), (
            "source_aggregator_service citation instructions must use relevance framing "
            "('cite every paper that is genuinely relevant') not a numeric floor."
        )

    def test_source_aggregator_says_do_not_pad(self):
        """Citation instructions must explicitly warn against padding."""
        import inspect
        import app.services.source_aggregator_service as svc
        src = inspect.getsource(svc)
        assert "do not pad" in src.lower() or "not pad" in src.lower(), (
            "Citation instructions must tell the LLM not to pad citations. "
            "A bare count floor ('at least 5') causes citation inflation."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Archetype-level strategy gating
# ══════════════════════════════════════════════════════════════════════════════

# Drug-specific strategy tokens that must never appear in research-tool output
_DRUG_STRATEGY_TOKENS = {
    "qidp", "lpad", "gain act", "pasteur", "510(k)", "510k", "de novo",
    "pma ", "ntap", "nda ", "bla ", "phase 1", "phase 2", "phase 3",
    "pediatric exclusivity", "breakthrough therapy", "fast track",
    "priority review", "accelerated approval",
}


def _strategy_text(sub_expert_id: str) -> str:
    from app.services.strategy_database import format_strategies_for_report
    items = format_strategies_for_report(sub_expert_id)
    return " ".join(
        " ".join([
            str(v) for v in item.values() if isinstance(v, str)
        ])
        for item in items
    ).lower()


class TestStrategyArchetypeGating:

    def test_research_tool_gets_no_universal_drug_device_strategies(self):
        """research_tool_non_clinical must not inherit the UNIVERSAL_STRATEGIES
        (FDA expedited designations, pediatric exclusivity, etc.)."""
        from app.services.strategy_database import _universal_for
        result = _universal_for("research_tool_non_clinical")
        assert result == [], (
            f"_universal_for('research_tool_non_clinical') must return [] — "
            f"got {len(result)} entries. Research tools have a dedicated domain list."
        )

    def test_research_infrastructure_gets_no_universal_strategies(self):
        from app.services.strategy_database import _universal_for
        result = _universal_for("research_infrastructure_saas")
        assert result == []

    def test_device_gets_device_universals_not_drug(self):
        """Device sub-experts must get UNIVERSAL_STRATEGIES_DEVICE, not drug strategies."""
        from app.services.strategy_database import _universal_for, UNIVERSAL_STRATEGIES_DEVICE
        result = _universal_for("device_cardiovascular")
        assert result == UNIVERSAL_STRATEGIES_DEVICE, (
            "device_cardiovascular must receive UNIVERSAL_STRATEGIES_DEVICE"
        )

    def test_drug_gets_drug_universals_not_device(self):
        """Drug sub-experts must get UNIVERSAL_STRATEGIES (drug playbook)."""
        from app.services.strategy_database import _universal_for, UNIVERSAL_STRATEGIES
        result = _universal_for("drug_amr")
        assert result == UNIVERSAL_STRATEGIES, (
            "drug_amr must receive UNIVERSAL_STRATEGIES (drug playbook)"
        )

    def test_research_tool_strategies_contain_no_drug_tokens(self):
        """Strategies returned for research_tool_non_clinical must not mention
        drug regulatory pathways, FDA drug submissions, or clinical trial phases."""
        text = _strategy_text("research_tool_non_clinical")
        leaked = [tok for tok in _DRUG_STRATEGY_TOKENS if tok in text]
        assert not leaked, (
            f"research_tool_non_clinical strategies contain drug/device vocabulary: {leaked!r}\n"
            f"Context (first 400 chars): {text[:400]!r}"
        )

    def test_research_infrastructure_strategies_contain_no_drug_tokens(self):
        text = _strategy_text("research_infrastructure_saas")
        leaked = [tok for tok in _DRUG_STRATEGY_TOKENS if tok in text]
        assert not leaked, (
            f"research_infrastructure_saas strategies contain drug/device vocabulary: {leaked!r}"
        )

    def test_research_tool_strategies_use_research_vocabulary(self):
        """Research tool strategies must anchor to the PI / lab / SBIR world."""
        text = _strategy_text("research_tool_non_clinical")
        research_terms = {"nih", "sbir", "pi ", "lab", "grant", "academic", "core facilit"}
        found = [t for t in research_terms if t in text]
        assert found, (
            "research_tool_non_clinical strategies must reference research-world terms "
            f"(NIH, SBIR, PI, lab, grant, academic). Found none. Text: {text[:200]!r}"
        )

    def test_drug_amr_strategies_use_amr_vocabulary(self):
        """AMR drug strategies must reference antibiotic-specific vocabulary."""
        text = _strategy_text("drug_amr")
        amr_terms = {"qidp", "lpad", "gain act", "barda", "antibiotic", "amr"}
        found = [t for t in amr_terms if t in text]
        assert found, (
            f"drug_amr strategies must contain AMR vocabulary. Found: {found!r}. "
            f"Text: {text[:300]!r}"
        )

    def test_strategy_count_not_inflated_for_research_tool(self):
        """Research tools should not receive padded strategy lists exceeding the
        real domain-specific entries."""
        from app.services.strategy_database import (
            DOMAIN_SPECIFIC_STRATEGIES, get_strategies_for_domain,
        )
        domain = DOMAIN_SPECIFIC_STRATEGIES.get("research_tool_non_clinical", [])
        returned = get_strategies_for_domain("research_tool_non_clinical", max_strategies=99)
        # Universal supplement must be 0 for research tools
        assert len(returned) == len(domain), (
            f"research_tool_non_clinical must return exactly its {len(domain)} "
            f"domain strategies, no universal filler. Got {len(returned)}."
        )

    def test_unknown_sub_expert_gets_drug_universals_not_research(self):
        """An unrecognised sub_expert_id falls back to UNIVERSAL_STRATEGIES (drug),
        which is the safer default vs. silently sending device or empty."""
        from app.services.strategy_database import _universal_for, UNIVERSAL_STRATEGIES
        result = _universal_for("completely_unknown_expert_xyz")
        assert result == UNIVERSAL_STRATEGIES, (
            "Unknown sub_expert_id must fall back to UNIVERSAL_STRATEGIES "
            "(drug playbook) as a safe default — not device or empty."
        )


# ══════════════════════════════════════════════════════════════════════════════
# _MIN_COMPARATORS is an honest-empty-state threshold, not a padding trigger
# ══════════════════════════════════════════════════════════════════════════════

class TestMinComparatorsIsHonestEmpty:
    """
    _MIN_COMPARATORS in competitive_intelligence_service is NOT a padding
    constraint — it triggers the honest-empty-state message when real
    competitors are scarce. This test confirms the semantic is correct.
    """

    def test_min_comparators_triggers_honest_empty_not_padding(self):
        import app.services.competitive_intelligence_service as svc
        import inspect
        src = inspect.getsource(svc)

        # Find the block that references _MIN_COMPARATORS
        idx = src.find("_MIN_COMPARATORS")
        context = src[max(0, idx - 50): idx + 300]
        context_lower = context.lower()

        # The context must reference honest empty state or manual research
        assert (
            "honest_empty" in context_lower or
            "honest empty" in context_lower or
            "manual" in context_lower or
            "no functional" in context_lower
        ), (
            "_MIN_COMPARATORS context must reference honest-empty-state semantics "
            "(not padding). Got context:\n" + context
        )

        # It must NOT reference padding or 'add more'
        assert "pad" not in context_lower and "add more" not in context_lower, (
            "_MIN_COMPARATORS must not be used to pad results. Context:\n" + context
        )
