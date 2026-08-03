"""
Rules 4+7 — Market template structure and three-directory separation tests.

Verifies:
  Rule 1  — Templates contain no numeric literals > 0.
  Rule 4  — Both templates compile against the same Axis, Gate, PriceTier,
             FunnelSpec types from app.market.types.
  Rule 7  — templates/, sources/, priors/ exist as separate directories.
             Numbers come from priors/; structure comes from templates/.
"""

from __future__ import annotations

import ast
import os
import importlib

import pytest

# ── paths ─────────────────────────────────────────────────────────────────────

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
_MARKET_DIR = os.path.join(_REPO_ROOT, "app", "market")
_TEMPLATES_DIR = os.path.join(_MARKET_DIR, "templates")
_SOURCES_DIR   = os.path.join(_MARKET_DIR, "sources")
_PRIORS_DIR    = os.path.join(_MARKET_DIR, "priors")


# ── Rule 7: three-directory structure exists ──────────────────────────────────

def test_templates_directory_exists():
    assert os.path.isdir(_TEMPLATES_DIR), "app/market/templates/ must exist (Rule 7)"


def test_sources_directory_exists():
    assert os.path.isdir(_SOURCES_DIR), "app/market/sources/ must exist (Rule 7)"


def test_priors_directory_exists():
    assert os.path.isdir(_PRIORS_DIR), "app/market/priors/ must exist (Rule 7)"


def test_both_template_files_exist():
    for name in ("life_sciences_research.py", "engineering_hardware.py"):
        path = os.path.join(_TEMPLATES_DIR, name)
        assert os.path.isfile(path), f"app/market/templates/{name} must exist (Rule 4)"


def test_both_priors_files_exist():
    for name in ("life_sciences_research.py", "engineering_hardware.py"):
        path = os.path.join(_PRIORS_DIR, name)
        assert os.path.isfile(path), f"app/market/priors/{name} must exist (Rule 7)"


# ── Rule 4: both templates import the same shared types ──────────────────────

def test_types_module_importable():
    from app.market import types  # noqa: F401


def test_life_sciences_research_template_importable():
    from app.market.templates import life_sciences_research  # noqa: F401


def test_engineering_hardware_template_importable():
    from app.market.templates import engineering_hardware  # noqa: F401


def test_both_templates_use_same_axis_type():
    from app.market.types import Axis
    from app.market.templates.life_sciences_research import TEMPLATE as LSR
    from app.market.templates.engineering_hardware import TEMPLATE as EH
    for ax in LSR.axes + EH.axes:
        assert isinstance(ax, Axis), (
            f"Axis '{ax.id}' is {type(ax).__name__}, not app.market.types.Axis (Rule 4)"
        )


def test_both_templates_use_same_gate_type():
    from app.market.types import Gate
    from app.market.templates.life_sciences_research import TEMPLATE as LSR
    from app.market.templates.engineering_hardware import TEMPLATE as EH
    for g in LSR.gates + EH.gates:
        assert isinstance(g, Gate), (
            f"Gate '{g.id}' is {type(g).__name__}, not app.market.types.Gate (Rule 4)"
        )


def test_both_templates_use_same_funnelspec_type():
    from app.market.types import FunnelSpec
    from app.market.templates.life_sciences_research import TEMPLATE as LSR
    from app.market.templates.engineering_hardware import TEMPLATE as EH
    assert isinstance(LSR, FunnelSpec)
    assert isinstance(EH, FunnelSpec)


# ── Rule 1: template files must contain no numeric literals > 0 ───────────────

def _numeric_literals_above_zero(filepath: str) -> list[tuple[int, float]]:
    """Return (line, value) for every numeric literal > 0 in the file."""
    with open(filepath, encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source, filename=filepath)
    found: list[tuple[int, float]] = []
    for node in ast.walk(tree):
        # Constant numeric literals
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            val = float(node.value)
            if val > 0.0:
                found.append((node.lineno, val))
        # Negative literals appear as UnaryOp(USub, Constant(...))
        elif (
            isinstance(node, ast.UnaryOp)
            and isinstance(node.op, ast.USub)
            and isinstance(node.operand, ast.Constant)
            and isinstance(node.operand.value, (int, float))
        ):
            val = float(node.operand.value)
            if val > 0.0:
                found.append((node.lineno, -val))
    return found


@pytest.mark.parametrize("template_name", [
    "life_sciences_research",
    "engineering_hardware",
])
def test_template_file_has_no_nonzero_numerics(template_name: str):
    """
    Template files must contain no numeric literals > 0.
    All numbers belong in priors/ (Rule 1).
    """
    path = os.path.join(_TEMPLATES_DIR, f"{template_name}.py")
    hits = _numeric_literals_above_zero(path)
    assert hits == [], (
        f"app/market/templates/{template_name}.py contains non-zero numeric literals "
        f"(Rule 1 — numbers belong in priors/):\n"
        + "\n".join(f"  line {ln}: {val}" for ln, val in hits)
    )


# ── FunnelSpec integrity checks ───────────────────────────────────────────────

@pytest.mark.parametrize("template_name,expected_domain", [
    ("life_sciences_research", "LIFE_SCIENCES_RESEARCH"),
    ("engineering_hardware",   "ENGINEERING_HARDWARE"),
])
def test_template_segment_domain(template_name: str, expected_domain: str):
    mod = importlib.import_module(f"app.market.templates.{template_name}")
    assert mod.TEMPLATE.segment_domain == expected_domain


@pytest.mark.parametrize("template_name", [
    "life_sciences_research",
    "engineering_hardware",
])
def test_funnel_chain_references_valid_axis_ids(template_name: str):
    mod = importlib.import_module(f"app.market.templates.{template_name}")
    spec = mod.TEMPLATE
    axis_ids = {a.id for a in spec.axes}
    for chain_id in spec.funnel_chain:
        assert chain_id in axis_ids, (
            f"funnel_chain entry '{chain_id}' is not a declared axis ID in "
            f"app/market/templates/{template_name}.py"
        )


@pytest.mark.parametrize("template_name", [
    "life_sciences_research",
    "engineering_hardware",
])
def test_all_axes_start_at_zero(template_name: str):
    mod = importlib.import_module(f"app.market.templates.{template_name}")
    for ax in mod.TEMPLATE.axes:
        assert ax.value == 0.0, (
            f"Axis '{ax.id}' in {template_name} template has value={ax.value} "
            f"(must be 0.0 in templates — numbers live in priors/)"
        )


@pytest.mark.parametrize("template_name", [
    "life_sciences_research",
    "engineering_hardware",
])
def test_all_gates_start_at_zero(template_name: str):
    mod = importlib.import_module(f"app.market.templates.{template_name}")
    for g in mod.TEMPLATE.gates:
        assert g.fraction == 0.0, (
            f"Gate '{g.id}' in {template_name} template has fraction={g.fraction} "
            f"(must be 0.0 in templates — numbers live in priors/)"
        )


@pytest.mark.parametrize("template_name", [
    "life_sciences_research",
    "engineering_hardware",
])
def test_all_price_tiers_start_at_zero(template_name: str):
    mod = importlib.import_module(f"app.market.templates.{template_name}")
    for t in mod.TEMPLATE.price_tiers:
        assert t.annual_usd == 0.0, (
            f"PriceTier '{t.id}' in {template_name} template has annual_usd={t.annual_usd} "
            f"(must be 0.0 in templates — numbers live in priors/)"
        )
        assert t.mix == 0.0, (
            f"PriceTier '{t.id}' in {template_name} template has mix={t.mix} "
            f"(must be 0.0 in templates — numbers live in priors/)"
        )


@pytest.mark.parametrize("template_name", [
    "life_sciences_research",
    "engineering_hardware",
])
def test_forbidden_vocabulary_is_nonempty(template_name: str):
    mod = importlib.import_module(f"app.market.templates.{template_name}")
    assert mod.TEMPLATE.clinical_vocabulary_forbidden, (
        f"{template_name} template must declare at least one forbidden vocabulary term"
    )


# ── apply_priors() integration ────────────────────────────────────────────────

def test_life_sciences_research_apply_priors_injects_values():
    from app.market.templates.life_sciences_research import TEMPLATE
    from app.market.priors.life_sciences_research import PRIORS

    spec = TEMPLATE.apply_priors(PRIORS)

    # Root axis: nih_funded_labs should have a value > 0 after priors applied
    nih_ax = spec.axis("nih_funded_labs")
    assert nih_ax.value > 0, "nih_funded_labs must have a positive value after apply_priors()"
    assert nih_ax.method == "modeled"

    # All four gates must have fraction > 0
    for gate_id in ("long_duration", "low_bandwidth", "not_custom", "budget_authority"):
        g = spec.gate(gate_id)
        assert g.fraction > 0.0, f"Gate '{gate_id}' still zero after apply_priors()"

    # Price tiers
    for tier_id in ("academic", "core_facility", "site_license"):
        t = spec.price_tier(tier_id)
        assert t.annual_usd > 0.0, f"PriceTier '{tier_id}' annual_usd still zero after apply_priors()"


def test_engineering_hardware_apply_priors_leaves_operator_required_zeros():
    from app.market.templates.engineering_hardware import TEMPLATE
    from app.market.priors.engineering_hardware import PRIORS

    spec = TEMPLATE.apply_priors(PRIORS)

    # total_sites must remain 0 — operator must supply this
    total = spec.axis("total_sites")
    assert total.value == 0.0, (
        "total_sites must remain 0.0 after apply_priors() — operator supplies this value"
    )
    assert "operator" in total.source.lower() or "⚠" in total.source, (
        "total_sites source must call out that operator must supply the value"
    )


def test_apply_priors_does_not_mutate_template():
    from app.market.templates.life_sciences_research import TEMPLATE
    from app.market.priors.life_sciences_research import PRIORS

    original_value = TEMPLATE.axis("nih_funded_labs").value
    _spec = TEMPLATE.apply_priors(PRIORS)
    assert TEMPLATE.axis("nih_funded_labs").value == original_value, (
        "apply_priors() must not mutate the original TEMPLATE object"
    )


def test_life_sciences_research_price_tier_mix_sums_to_one():
    from app.market.templates.life_sciences_research import TEMPLATE
    from app.market.priors.life_sciences_research import PRIORS

    spec = TEMPLATE.apply_priors(PRIORS)
    total_mix = sum(t.mix for t in spec.price_tiers)
    assert abs(total_mix - 1.0) < 0.001, (
        f"life_sciences_research price tier mix must sum to 1.0, got {total_mix:.4f}"
    )


def test_life_sciences_research_priors_match_market_segmentation_constants():
    """
    Priors must be consistent with the existing market_segmentation.py constants
    (both reference the same underlying Carnegie + HERD survey data).
    """
    from app.market.priors.life_sciences_research import PRIORS

    gates = PRIORS["gates"]

    assert abs(gates["long_duration"]["fraction"] - 0.22) < 0.001, (
        "long_duration gate fraction should match FRAC_LONG_DURATION=0.22 from market_segmentation.py"
    )
    assert abs(gates["low_bandwidth"]["fraction"] - 0.81) < 0.001, (
        "low_bandwidth gate fraction should match FRAC_LOW_BANDWIDTH=0.81 from market_segmentation.py"
    )
    assert abs(gates["not_custom"]["fraction"] - 0.63) < 0.001, (
        "not_custom gate fraction should match FRAC_NOT_CUSTOM=0.63 from market_segmentation.py"
    )
    assert abs(gates["budget_authority"]["fraction"] - 0.47) < 0.001, (
        "budget_authority gate fraction should match FRAC_BUDGET_AUTH=0.47 from market_segmentation.py"
    )

    tiers = PRIORS["price_tiers"]
    assert tiers["academic"]["annual_usd"]      == 7_000.0
    assert tiers["core_facility"]["annual_usd"] == 20_000.0
    assert tiers["site_license"]["annual_usd"]  == 45_000.0
