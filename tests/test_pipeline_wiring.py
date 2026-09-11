"""
Pipeline wiring guard — ensures the production report path stays correct.

Root cause of past "features never appear in reports" bug:
  New features were added to market_sizing_orchestrator.py, which is DEAD CODE.
  The real pipeline calls market_sizing_derivation_service.py directly from
  alignment_service.py. The orchestrator is never imported by alignment_service.

These tests will fail loudly if someone accidentally re-wires the wrong module.
"""

import ast
import pathlib

ROOT = pathlib.Path(__file__).parent.parent

ALIGNMENT   = ROOT / "app" / "services" / "alignment_service.py"
DERIV_SVC   = ROOT / "app" / "services" / "market_sizing_derivation_service.py"
ORCHESTRATOR = ROOT / "app" / "services" / "market_sizing_orchestrator.py"


def _imported_names(path: pathlib.Path) -> set[str]:
    """Return all module names imported (directly or from) in a file."""
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    return names


def test_alignment_service_does_not_import_orchestrator():
    """alignment_service must NEVER import market_sizing_orchestrator.
    If this fails, features added to the orchestrator will appear in reports
    but any feature added to the derivation service won't — reproducing the
    original 'features never show up' bug."""
    imports = _imported_names(ALIGNMENT)
    assert "app.services.market_sizing_orchestrator" not in imports, (
        "alignment_service.py is importing market_sizing_orchestrator — "
        "this is WRONG. Add features to market_sizing_derivation_service instead."
    )


def test_alignment_service_imports_derivation_service():
    """alignment_service must import from market_sizing_derivation_service.
    This is the real production path."""
    src = ALIGNMENT.read_text()
    assert "market_sizing_derivation_service" in src, (
        "alignment_service.py no longer imports market_sizing_derivation_service — "
        "the production market sizing pipeline is broken."
    )


def test_derivation_service_wires_triangulator():
    """market_sizing_derivation_service must call the triangulator so
    cross-validation appears in every report."""
    src = DERIV_SVC.read_text()
    assert "market_sizing_triangulator" in src, (
        "market_sizing_derivation_service no longer imports market_sizing_triangulator — "
        "triangulation will not appear in reports."
    )


def test_format_derivation_for_prompt_includes_cross_validation():
    """The prompt builder must emit the CROSS-VALIDATION block."""
    from app.services.market_sizing_derivation_service import (
        generate_market_sizing_derivation,
        format_derivation_for_prompt,
    )
    d = generate_market_sizing_derivation(
        idea="mRNA vaccine for influenza",
        product_type="vaccine",
        disease_name="influenza",
        therapeutic_area="vaccine",
        us_patient_population=50_000_000,
    )
    prompt = format_derivation_for_prompt(d)
    assert "CROSS-VALIDATION" in prompt, "CROSS-VALIDATION block missing from prompt"
    assert "SOURCES" in prompt, "SOURCES block missing from prompt"


def test_format_derivation_for_prompt_includes_citations():
    """The prompt builder must list primary citations so Claude can cite them."""
    from app.services.market_sizing_derivation_service import (
        generate_market_sizing_derivation,
        format_derivation_for_prompt,
    )
    d = generate_market_sizing_derivation(
        idea="Lab flow cytometer for immunology research",
        product_type="other",
        disease_name="",
        therapeutic_area="neuroscience",
        us_patient_population=0,
        sub_expert_id="research_tool_non_clinical",
    )
    prompt = format_derivation_for_prompt(d)
    assert "[NIH RePORTER]" in prompt, "NIH RePORTER citation missing"
    assert "[NSF Award Search]" in prompt, "NSF Award Search citation missing"
