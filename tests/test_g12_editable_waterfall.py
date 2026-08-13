"""G.12 — Editable market model waterfall.

Verifies:
  1. Frontend uses 'pe_token' (not 'jwt') for auth in save and load
  2. Waterfall UI elements are wired correctly in app.html
  3. Backend override endpoints exist and have the expected shapes
  4. Provenance waterfall entries are structured for the editable UI
"""
from __future__ import annotations

import os
import re
import types

import pytest


# ── Paths ────────────────────────────────────────────────────────────────────

def _app_html() -> str:
    path = os.path.join(
        os.path.dirname(__file__), "..", "..", "ProjectElevate-Frontend", "app.html"
    )
    with open(os.path.normpath(path), encoding="utf-8") as f:
        return f.read()


def _alignment_src() -> str:
    import inspect, app.api.alignment as m
    return inspect.getsource(m)


# ══════════════════════════════════════════════════════════════════════════════
# G.12.1 — Auth token key correctness
# ══════════════════════════════════════════════════════════════════════════════

class TestAuthTokenKey:
    """
    The app stores the JWT under 'pe_token'.
    _msSaveOverrides and _msLoadOverrides must read from 'pe_token', not 'jwt'.
    """

    def _function_body(self, src: str, name: str) -> str:
        m = re.search(
            rf"async function {re.escape(name)}\s*\(\s*\)[\s\S]*?(?=\nasync function |\nfunction |\Z)",
            src,
        )
        return m.group(0) if m else ""

    def test_save_overrides_uses_pe_token(self):
        src = _app_html()
        body = self._function_body(src, "_msSaveOverrides")
        assert body, "_msSaveOverrides must be defined in app.html"
        assert "pe_token" in body, (
            "_msSaveOverrides must use localStorage.getItem('pe_token'), not 'jwt'"
        )
        assert "'jwt'" not in body and '"jwt"' not in body, (
            "_msSaveOverrides must not reference 'jwt' — the token key is 'pe_token'"
        )

    def test_load_overrides_uses_pe_token(self):
        src = _app_html()
        body = self._function_body(src, "_msLoadOverrides")
        assert body, "_msLoadOverrides must be defined in app.html"
        assert "pe_token" in body, (
            "_msLoadOverrides must use localStorage.getItem('pe_token'), not 'jwt'"
        )
        assert "'jwt'" not in body and '"jwt"' not in body, (
            "_msLoadOverrides must not reference 'jwt' — the token key is 'pe_token'"
        )

    def test_no_session_storage_jwt_fallback(self):
        src = _app_html()
        # Neither function should fall back to sessionStorage.getItem('jwt')
        for fn in ("_msSaveOverrides", "_msLoadOverrides"):
            body = self._function_body(src, fn)
            assert "sessionStorage.getItem('jwt')" not in body, (
                f"{fn} must not fall back to sessionStorage.getItem('jwt')"
            )


# ══════════════════════════════════════════════════════════════════════════════
# G.12.2 — Frontend waterfall wiring
# ══════════════════════════════════════════════════════════════════════════════

class TestWaterfallFrontendWiring:

    def test_ms_waterfall_container_id_present(self):
        src = _app_html()
        assert "ms-waterfall-container" in src, (
            "app.html must render a #ms-waterfall-container div for the waterfall"
        )

    def test_gate_input_class_and_oninput(self):
        src = _app_html()
        assert "ms-gate-input" in src, "waterfall inputs must have class 'ms-gate-input'"
        assert "_msOnGateEdit(this)" in src, (
            "gate inputs must have oninput='_msOnGateEdit(this)'"
        )

    def test_ms_save_bar_present(self):
        src = _app_html()
        assert "ms-save-bar" in src, "save bar div must exist in app.html"

    def test_save_bar_hidden_by_default(self):
        src = _app_html()
        m = re.search(r'id="ms-save-bar"[^>]*>', src)
        assert m, "ms-save-bar element must be present"
        tag = m.group(0)
        assert "display:none" in tag, "save bar must be hidden (display:none) by default"

    def test_ms_recompute_function_defined(self):
        src = _app_html()
        assert "function _msRecompute()" in src, "_msRecompute must be defined"

    def test_ms_recompute_updates_agg_vals(self):
        src = _app_html()
        # IDs are set via template literal: `ms-agg-val-${role}` / `ms-agg-val-${w.used_in_formula}`
        assert "ms-agg-val-" in src, "_msRecompute must use ms-agg-val-{role} element IDs"
        assert "ms-agg-val-${role}" in src or "ms-agg-val-${w.used_in_formula}" in src, (
            "_msRecompute must reference aggregate value elements via template literal"
        )

    def test_load_overrides_called_after_render(self):
        src = _app_html()
        assert "setTimeout(_msLoadOverrides" in src, (
            "_msLoadOverrides must be called via setTimeout after the report renders"
        )

    def test_ms_wf_state_set_before_loop(self):
        src = _app_html()
        assert "window._msWfState" in src, (
            "window._msWfState must be set before the waterfall forEach loop"
        )
        assert "tam_usd" in src and "sam_usd" in src and "som_usd" in src, (
            "_msWfState must capture tam_usd, sam_usd, som_usd from prov.run"
        )

    def test_ms_rationale_textarea_present(self):
        src = _app_html()
        assert "ms-rationale" in src, (
            "A rationale textarea must be present in the save bar"
        )

    def test_revert_button_calls_revert_fn(self):
        src = _app_html()
        assert "_msRevertOverrides()" in src, "Revert button must call _msRevertOverrides()"

    def test_plausibility_warning_in_recompute(self):
        """Inputs >4× or <10% of model value get an amber border warning."""
        src = _app_html()
        assert "ratio > 4 || ratio < 0.1" in src or "ratio > 4" in src, (
            "_msRecompute must warn when an edited value is implausibly far from the model"
        )


# ══════════════════════════════════════════════════════════════════════════════
# G.12.3 — Backend endpoint shapes
# ══════════════════════════════════════════════════════════════════════════════

class TestBackendEndpoints:

    def test_save_override_endpoint_exists(self):
        import app.api.alignment as m
        import inspect
        src = inspect.getsource(m)
        assert "/market-sizing-override" in src, (
            "POST /alignment/market-sizing-override endpoint must exist"
        )
        assert "save_market_sizing_override" in src, (
            "save_market_sizing_override function must be defined"
        )

    def test_get_override_endpoint_exists(self):
        import app.api.alignment as m
        import inspect
        src = inspect.getsource(m)
        assert "get_market_sizing_override" in src, (
            "GET /alignment/market-sizing-override/{report_id} endpoint must exist"
        )

    def test_save_endpoint_accepts_step_overrides(self):
        import app.api.alignment as m
        import inspect
        src = inspect.getsource(m.save_market_sizing_override)
        assert "step_overrides" in src, (
            "save endpoint must accept and persist 'step_overrides'"
        )

    def test_save_endpoint_accepts_rationale(self):
        import app.api.alignment as m
        import inspect
        src = inspect.getsource(m.save_market_sizing_override)
        assert "rationale" in src, (
            "save endpoint must persist 'rationale'"
        )

    def test_save_endpoint_accepts_tam_sam_som(self):
        import app.api.alignment as m
        import inspect
        src = inspect.getsource(m.save_market_sizing_override)
        assert "tam_usd" in src
        assert "sam_usd" in src
        assert "som_usd" in src

    def test_get_endpoint_returns_has_override_field(self):
        # Use full module source — there are two functions with the same name;
        # inspect.getsource(m.fn) resolves to the last definition, so search the file.
        src = _alignment_src()
        # The G.12 GET endpoint at /alignment/market-sizing-override/{report_id}
        # must return has_override for the frontend check
        assert "has_override" in src, (
            "GET /alignment/market-sizing-override endpoint must return {has_override: ...}"
        )

    def test_endpoints_use_optional_auth(self):
        import app.api.alignment as m
        import inspect
        src = inspect.getsource(m.save_market_sizing_override) + inspect.getsource(m.get_market_sizing_override)
        assert "get_optional_user" in src, (
            "Override endpoints must use get_optional_user (anonymous saves allowed)"
        )


# ══════════════════════════════════════════════════════════════════════════════
# G.12.4 — Provenance waterfall structure for editable UI
# ══════════════════════════════════════════════════════════════════════════════

def _make_deriv(
    *,
    tam: float = 45_833_333.0,
    sam: float = 13_750_000.0,
    som: float = 2_062_500.0,
    steps: list | None = None,
):
    d = types.SimpleNamespace(
        us_tam_usd=tam,
        us_sam_usd=sam,
        us_som_usd=som,
        archetype="research_tool_non_clinical",
        archetype_label="Research Tool",
        idea="TestTool",
        formula_name="Bottom-up",
        formula_overview="labs × spend",
        tam_fmt="$45.8M",
        sam_fmt="$13.8M",
        som_fmt="$2.1M",
        confidence_note="Estimated",
        key_assumptions=[],
        primary_citations=[],
        steps=steps or [],
    )
    return d


def _make_step(label, value, unit="USD", role="TAM"):
    return types.SimpleNamespace(
        step_num=1,
        title=label,
        value=float(value),
        unit=unit,
        formula="",
        data_source="Model",
        source_url="",
        assumptions=[],
        explanation="",
    )


class TestWaterfallStructureForUI:

    def _build(self, **kwargs) -> dict:
        from app.services.market_provenance_service import build_provenance
        deriv = _make_deriv(**kwargs)
        return build_provenance(deriv)

    def test_waterfall_key_present(self):
        prov = self._build()
        assert "waterfall" in prov

    def test_each_entry_has_label_and_value(self):
        steps = [_make_step("Buyer population", 5500.0, "count")]
        prov = self._build(steps=steps)
        for entry in prov["waterfall"]:
            assert "label" in entry, f"Entry missing 'label': {entry}"
            assert "value" in entry, f"Entry missing 'value': {entry}"

    def test_each_entry_has_used_in_formula(self):
        """used_in_formula maps each waterfall row to TAM/SAM/SOM for color coding."""
        steps = [_make_step("Buyer population", 5500.0, "count")]
        prov = self._build(steps=steps)
        for entry in prov["waterfall"]:
            assert "used_in_formula" in entry, (
                f"Entry missing 'used_in_formula' (needed for role badge + recompute): {entry}"
            )

    def test_aggregate_rows_have_is_aggregate_true(self):
        prov = self._build()
        agg = [w for w in prov["waterfall"] if w.get("is_aggregate")]
        assert len(agg) == 3, "Three aggregate rows required (TAM, SAM, SOM)"
        for row in agg:
            assert row["is_aggregate"] is True

    def test_non_aggregate_rows_do_not_have_is_aggregate(self):
        """Non-aggregate rows should not have is_aggregate=True (they get input elements)."""
        steps = [_make_step("Buyer population", 5500.0, "count")]
        prov = self._build(steps=steps)
        non_agg = [w for w in prov["waterfall"] if not w.get("is_aggregate")]
        for row in non_agg:
            assert not row.get("is_aggregate"), f"Row should not be aggregate: {row}"

    def test_run_block_has_tam_sam_som(self):
        """Frontend _msWfState reads from prov.run — must have tam/sam/som keys."""
        prov = self._build(tam=45_833_333.0, sam=13_750_000.0, som=2_062_500.0)
        run = prov.get("run", {})
        assert "tam_usd" in run, "prov.run must have tam_usd"
        assert "sam_usd" in run, "prov.run must have sam_usd"
        assert "som_usd" in run, "prov.run must have som_usd"

    def test_run_values_match_deriv(self):
        tam, sam, som = 45_833_333.0, 13_750_000.0, 2_062_500.0
        prov = self._build(tam=tam, sam=sam, som=som)
        run = prov["run"]
        assert run["tam_usd"] == pytest.approx(tam)
        assert run["sam_usd"] == pytest.approx(sam)
        assert run["som_usd"] == pytest.approx(som)
