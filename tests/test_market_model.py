"""Spec v9 Part 9 — MarketModel tests.

Tests map 1-to-1 with the spec's Part 9 list, plus additional coverage
for the Node/formula/graph internals that the spec's acceptance criteria
depend on.
"""
from __future__ import annotations

import pytest

from app.model.nodes import Node, Citation
from app.model.formulas import resolve, dependencies, _eval_formula
from app.model.graph import assert_acyclic, build_edges, affected
from app.model.market_model import MarketModel, _new_id, _utcnow
from app.model.extract import extract_model_from_flat, _standard_nodes


# ── fixtures ─────────────────────────────────────────────────────────────────

def _hublink_nodes() -> dict[str, Node]:
    return _standard_nodes(
        pop=55_000, spend=1_250,
        sam_rate=0.40, som_rate=0.165,
        pop_low=30_000, pop_high=80_000,
        sp_low=500, sp_high=2_000,
        sam_low=0.25, sam_high=0.55,
        som_low=0.08, som_high=0.25,
    )


def _build(nodes: dict[str, Node] | None = None, report_id: str = "rpt_test") -> MarketModel:
    return MarketModel(
        id=_new_id(),
        report_id=report_id,
        version=1,
        parent_version=None,
        nodes=nodes or _hublink_nodes(),
        created_at=_utcnow(),
        created_by="engine",
    )


HUBLINK = _build


# ══════════════════════════════════════════════════════════════════════════════
# Node — construction invariants
# ══════════════════════════════════════════════════════════════════════════════

class TestNodeInvariants:

    def test_raw_value_only(self):
        n = Node(id="x", label="X", unit="USD", raw_value=100.0)
        assert n.raw_value == 100.0
        assert n.formula is None

    def test_formula_only(self):
        n = Node(id="x", label="X", unit="USD", formula="a * b")
        assert n.formula == "a * b"
        assert n.raw_value is None

    def test_both_raises(self):
        with pytest.raises(ValueError, match="exactly one"):
            Node(id="x", label="X", unit="USD", raw_value=1.0, formula="a * b")

    def test_neither_raises(self):
        with pytest.raises(ValueError, match="exactly one"):
            Node(id="x", label="X", unit="USD")

    def test_retrieved_without_source_raises(self):
        with pytest.raises(ValueError, match="source"):
            Node(id="x", label="X", unit="USD", raw_value=1.0, method="retrieved")

    def test_retrieved_with_source_ok(self):
        n = Node(
            id="x", label="X", unit="USD", raw_value=1.0, method="retrieved",
            source=Citation("NIH", "https://nih.gov", "2025-01-01"),
        )
        assert n.method == "retrieved"

    def test_round_trip(self):
        n = Node(
            id="buyer_population", label="Labs", unit="labs",
            raw_value=55_000, method="assumed", low=30_000, high=80_000,
            ui_control="slider", ui_min=100, ui_max=200_000, ui_step=100,
            rationale="NIH RePORTER estimate.",
        )
        assert Node.from_dict(n.to_dict()) == n


# ══════════════════════════════════════════════════════════════════════════════
# Formula evaluator
# ══════════════════════════════════════════════════════════════════════════════

class TestFormulaEvaluator:

    def _nodes(self, **kw) -> dict[str, Node]:
        return {
            k: Node(id=k, label=k, unit="USD", raw_value=float(v))
            for k, v in kw.items()
        }

    def test_multiplication(self):
        nodes = self._nodes(a=10, b=3)
        assert _eval_formula("a * b", nodes, {}) == 30.0

    def test_addition(self):
        nodes = self._nodes(a=5, b=7)
        assert _eval_formula("a + b", nodes, {}) == 12.0

    def test_division(self):
        nodes = self._nodes(a=100, b=4)
        assert _eval_formula("a / b", nodes, {}) == 25.0

    def test_constant_in_formula(self):
        nodes = self._nodes(a=10)
        assert _eval_formula("a * 3", nodes, {}) == 30.0

    def test_unknown_node_raises(self):
        nodes = self._nodes(a=10)
        with pytest.raises(KeyError, match="unknown node"):
            _eval_formula("a * z", nodes, {})

    def test_function_call_rejected(self):
        nodes = self._nodes(a=10)
        with pytest.raises(ValueError, match="disallowed"):
            _eval_formula("abs(a)", nodes, {})

    def test_string_constant_rejected(self):
        nodes = self._nodes(a=10)
        with pytest.raises(ValueError, match="non-numeric"):
            _eval_formula("'hello'", nodes, {})

    def test_dependencies(self):
        assert dependencies("buyer_population * spend_per_unit") == {
            "buyer_population", "spend_per_unit"
        }

    def test_cache_prevents_double_evaluation(self):
        call_count = [0]
        nodes = self._nodes(a=5, b=3)
        cache: dict = {}
        resolve("a", nodes, cache)
        resolve("a", nodes, cache)  # should hit cache
        assert "a" in cache


# ══════════════════════════════════════════════════════════════════════════════
# Graph
# ══════════════════════════════════════════════════════════════════════════════

class TestGraph:

    def test_build_edges_simple(self):
        nodes = {
            "a": Node(id="a", label="A", unit="x", raw_value=10.0),
            "b": Node(id="b", label="B", unit="x", formula="a * 2"),
        }
        edges = build_edges(nodes)
        assert "b" in edges["a"]

    def test_cycle_detected(self):
        nodes = {
            "a": Node(id="a", label="A", unit="x", formula="b * 2"),
            "b": Node(id="b", label="B", unit="x", formula="a * 2"),
        }
        with pytest.raises(ValueError, match="[Cc]ycle"):
            assert_acyclic(nodes)

    def test_missing_dep_raises(self):
        nodes = {
            "a": Node(id="a", label="A", unit="x", formula="missing_node * 2"),
        }
        with pytest.raises((KeyError, ValueError)):
            assert_acyclic(nodes)

    def test_affected_chain(self):
        # a → b → c
        nodes = {
            "a": Node(id="a", label="A", unit="x", raw_value=1.0),
            "b": Node(id="b", label="B", unit="x", formula="a * 2"),
            "c": Node(id="c", label="C", unit="x", formula="b * 3"),
        }
        edges = build_edges(nodes)
        aff = affected("a", edges)
        assert set(aff) == {"a", "b", "c"}
        # b must come before c in the ordering
        assert aff.index("b") < aff.index("c")


# ══════════════════════════════════════════════════════════════════════════════
# MarketModel — Part 9 spec tests
# ══════════════════════════════════════════════════════════════════════════════

class TestMarketModelSpec:
    """Direct implementations of spec Part 9."""

    def test_model_is_pure_function_of_nodes(self):
        """Two models with identical nodes must produce identical values."""
        m1 = HUBLINK()
        m2 = HUBLINK()
        assert m1.values() == m2.values()

    def test_override_recomputes_downstream(self):
        m = HUBLINK()
        m2 = m.with_override("spend_per_unit", 8_000, "Our labs budget ~$8k/yr", "u1")
        assert m2.value("tam") == pytest.approx(m2.value("buyer_population") * 8_000)
        assert m2.value("som") == pytest.approx(m2.value("sam") * m2.value("som_rate"))

    def test_override_is_immutable(self):
        """with_override must not mutate the original."""
        m = HUBLINK()
        before = m.values()
        m.with_override("spend_per_unit", 8_000, "r", "u1")
        assert m.values() == before

    def test_gate_multiplies_target(self):
        m = HUBLINK()
        gate = Node(
            id="gate_iacuc",
            label="Labs with IACUC-approved vivarium",
            unit="ratio",
            raw_value=0.6,
            method="user_gate",
        )
        m2 = m.with_gate("buyer_population", gate)
        assert m2.value("buyer_population") == pytest.approx(m.value("buyer_population") * 0.6)
        # Gate propagates to TAM (buyer_population is an input to TAM)
        assert m2.value("tam") == pytest.approx(m.value("tam") * 0.6)

    def test_sam_cannot_exceed_tam(self):
        """Core invariant: SAM > TAM must raise at construction time."""
        m = HUBLINK()
        with pytest.raises(AssertionError, match="SAM"):
            m.with_override("sam_rate", 1.5, "test override", "u1")

    def test_version_chain_intact(self):
        m1 = HUBLINK()
        m2 = m1.with_override("spend_per_unit", 8_000, "r", "u")
        m3 = m2.with_override("sam_rate", 0.3, "r", "u")
        assert m3.version == 3
        assert m3.parent_version == 2
        assert m2.parent_version == 1

    def test_blocked_model_still_has_hash(self):
        """A model hash must exist even before the export check — used on draft PDFs."""
        m = HUBLINK()
        h = m.model_hash()
        assert h.startswith("sha256:")
        assert len(h) > 10

    def test_model_hash_is_stable(self):
        """Same nodes always produce the same hash."""
        m1 = HUBLINK()
        m2 = HUBLINK()
        assert m1.model_hash() == m2.model_hash()

    def test_model_hash_changes_on_override(self):
        m = HUBLINK()
        m2 = m.with_override("spend_per_unit", 8_000, "r", "u")
        assert m.model_hash() != m2.model_hash()


# ══════════════════════════════════════════════════════════════════════════════
# Override mechanics
# ══════════════════════════════════════════════════════════════════════════════

class TestOverride:

    def test_non_editable_node_raises(self):
        m = HUBLINK()
        with pytest.raises(PermissionError):
            m.with_override("tam", 999_999, "force TAM", "u1")

    def test_override_value_survives_serialise(self):
        m = HUBLINK()
        m2 = m.with_override("spend_per_unit", 8_000, "eight k", "u1")
        d = m2.to_dict()
        m3 = MarketModel.from_dict(d)
        assert m3.value("spend_per_unit") == 8_000

    def test_reset_node_clears_override(self):
        m = HUBLINK()
        m2 = m.with_override("spend_per_unit", 8_000, "r", "u")
        m3 = m2.reset_node("spend_per_unit")
        assert m3.value("spend_per_unit") == m.value("spend_per_unit")

    def test_gates_still_apply_after_override(self):
        """User sets override on buyer_population; gate still multiplies it."""
        m = HUBLINK()
        gate = Node(id="g_vivarium", label="IACUC", unit="ratio", raw_value=0.6, method="user_gate")
        m2 = m.with_gate("buyer_population", gate)
        m3 = m2.with_override("buyer_population", 20_000, "direct correction", "u")
        assert m3.value("buyer_population") == pytest.approx(20_000 * 0.6)

    def test_som_cannot_exceed_sam(self):
        m = HUBLINK()
        with pytest.raises(AssertionError, match="SOM"):
            m.with_override("som_rate", 1.5, "r", "u")


# ══════════════════════════════════════════════════════════════════════════════
# Gate mechanics
# ══════════════════════════════════════════════════════════════════════════════

class TestGate:

    def test_gate_requires_ratio_unit(self):
        m = HUBLINK()
        bad_gate = Node(id="g_bad", label="Bad", unit="labs", raw_value=0.5, method="user_gate")
        with pytest.raises(ValueError, match="ratio"):
            m.with_gate("buyer_population", bad_gate)

    def test_without_gate_removes_it(self):
        m = HUBLINK()
        gate = Node(id="g_rm", label="RM", unit="ratio", raw_value=0.5, method="user_gate")
        m2 = m.with_gate("buyer_population", gate)
        m3 = m2.without_gate("g_rm")
        assert m3.value("buyer_population") == pytest.approx(m.value("buyer_population"))
        assert "g_rm" not in m3.nodes

    def test_multiple_gates_multiply(self):
        m = HUBLINK()
        g1 = Node(id="g1", label="G1", unit="ratio", raw_value=0.8, method="user_gate")
        g2 = Node(id="g2", label="G2", unit="ratio", raw_value=0.5, method="user_gate")
        m2 = m.with_gate("buyer_population", g1).with_gate("buyer_population", g2)
        expected = m.value("buyer_population") * 0.8 * 0.5
        assert m2.value("buyer_population") == pytest.approx(expected)


# ══════════════════════════════════════════════════════════════════════════════
# Diff
# ══════════════════════════════════════════════════════════════════════════════

class TestDiff:

    def test_diff_shows_changed_nodes(self):
        m = HUBLINK()
        m2 = m.with_override("spend_per_unit", 8_000, "r", "u")
        diff = m.diff(m2)
        assert "spend_per_unit" in diff
        assert "tam" in diff
        assert diff["spend_per_unit"]["from"] == pytest.approx(1_250)
        assert diff["spend_per_unit"]["to"]   == pytest.approx(8_000)

    def test_diff_pct_calculation(self):
        m = HUBLINK()
        m2 = m.with_override("spend_per_unit", 2_500, "doubling spend", "u")
        diff = m.diff(m2)
        assert diff["spend_per_unit"]["pct"] == pytest.approx(100.0, abs=0.1)

    def test_diff_empty_when_no_change(self):
        m = HUBLINK()
        assert m.diff(m) == {}


# ══════════════════════════════════════════════════════════════════════════════
# Extract adapter
# ══════════════════════════════════════════════════════════════════════════════

class TestExtractAdapter:

    def test_extract_from_flat_produces_correct_tam(self):
        flat = {
            "pop_lo": 40_000, "pop_hi": 70_000,
            "sp_lo": 1_000,   "sp_hi": 1_500,
            "sam_lo": 0.30,   "sam_hi": 0.50,
            "som_lo": 0.10,   "som_hi": 0.20,
        }
        m = extract_model_from_flat(flat, "rpt_x")
        pop_mid   = (40_000 + 70_000) / 2   # 55_000
        spend_mid = (1_000 + 1_500)   / 2   # 1_250
        assert m.value("tam") == pytest.approx(pop_mid * spend_mid)

    def test_extract_respects_sam_rate(self):
        flat = {
            "pop_lo": 1_000, "pop_hi": 3_000,
            "sp_lo": 1_000,  "sp_hi": 1_000,
            "sam_lo": 0.30,  "sam_hi": 0.50,
            "som_lo": 0.10,  "som_hi": 0.20,
        }
        m = extract_model_from_flat(flat, "rpt_y")
        assert m.value("sam") == pytest.approx(m.value("tam") * 0.40)

    def test_extract_invariants_hold(self):
        """The extracted model must pass SAM ≤ TAM — if it doesn't the data is broken."""
        flat = {
            "pop_lo": 1_000, "pop_hi": 3_000,
            "sp_lo": 500,    "sp_hi": 1_000,
            "sam_lo": 0.30,  "sam_hi": 0.50,
            "som_lo": 0.05,  "som_hi": 0.15,
        }
        m = extract_model_from_flat(flat, "rpt_z")
        v = m.values()
        assert v["sam"] <= v["tam"] + 1e-6
        assert v["som"] <= v["sam"] + 1e-6

    def test_standard_nodes_all_seven_present(self):
        nodes = _standard_nodes(55_000, 1_250, 0.40, 0.165)
        assert set(nodes.keys()) == {
            "buyer_population", "spend_per_unit", "tam",
            "sam_rate", "sam", "som_rate", "som",
        }

    def test_derived_nodes_not_editable(self):
        nodes = _standard_nodes(55_000, 1_250, 0.40, 0.165)
        assert not nodes["tam"].editable
        assert not nodes["sam"].editable
        assert not nodes["som"].editable

    def test_input_nodes_editable(self):
        nodes = _standard_nodes(55_000, 1_250, 0.40, 0.165)
        assert nodes["buyer_population"].editable
        assert nodes["spend_per_unit"].editable
        assert nodes["sam_rate"].editable
        assert nodes["som_rate"].editable


# ══════════════════════════════════════════════════════════════════════════════
# Formatted values
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatted:

    def test_tam_formatted_as_millions(self):
        m = HUBLINK()  # tam = 55_000 * 1_250 = $68.75M
        fmt = m.formatted()
        assert "M" in fmt["tam"] or "B" in fmt["tam"]
        assert fmt["tam"].startswith("$")

    def test_buyer_population_formatted_as_integer(self):
        m = HUBLINK()
        fmt = m.formatted()
        assert "," in fmt["buyer_population"] or fmt["buyer_population"].isdigit()
        assert "$" not in fmt["buyer_population"]

    def test_sam_rate_formatted_as_percent(self):
        m = HUBLINK()
        fmt = m.formatted()
        assert "%" in fmt["sam_rate"]
