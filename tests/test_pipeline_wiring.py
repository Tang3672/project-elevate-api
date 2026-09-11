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


# ─────────────────────────────────────────────────────────────────────────────
# Bibliography wiring guard
#
# Root cause of the "only 6 sources appear in the report" bug:
#   _generate_expert_report() builds the full pipeline bibliography via
#   collect_all_citations() (live SBIR awards, preprints, patents, competitor
#   trials, aggregated papers, EDGAR filings). generate_pi_report() then called
#   build_sources_from_report(), which rebuilds report.sources from structured
#   report fields ONLY and silently discarded every pipeline source.
#
# The failure was invisible — no exception, just a short bibliography.
# ─────────────────────────────────────────────────────────────────────────────

def test_build_sources_from_report_discards_pipeline_sources():
    """
    Documents the upstream behaviour the merge in generate_pi_report compensates
    for. If build_sources_from_report ever starts preserving incoming sources,
    this test fails and the merge block can be simplified.
    """
    from app.services.source_formatter import build_sources_from_report
    pipeline = [{"number": 1, "name": "SBIR Award (FY2026): X — NeuroCo",
                 "url": "https://reporter.nih.gov/project-details/10812345"}]
    out = build_sources_from_report({"sources": list(pipeline)})
    surviving = {s.get("url") for s in out.get("sources", [])}
    assert pipeline[0]["url"] not in surviving, (
        "build_sources_from_report now preserves pipeline sources — "
        "the re-append block in generate_pi_report may no longer be needed"
    )


def test_generate_pi_report_reappends_pipeline_bibliography():
    """
    generate_pi_report must stash report.sources before build_sources_from_report
    and re-append what was dropped. Without this, every live-fetched citation
    (SBIR, preprints, patents, competitor trials) vanishes from the report.
    """
    src = ALIGNMENT.read_text()
    assert "_pipeline_bib" in src, (
        "generate_pi_report no longer stashes the pipeline bibliography — "
        "collect_all_citations() output will be silently discarded"
    )
    stash = src.index("_pipeline_bib = ")
    rebuild = src.index("build_sources_from_report(report_dict)")
    assert stash < rebuild, "pipeline bibliography must be captured BEFORE the rebuild"


def test_collect_all_citations_receives_every_pipeline_source():
    """
    Every live data source with URLs must be passed to collect_all_citations().
    Dropping a kwarg here is how sources silently stop appearing.
    """
    import inspect
    from app.services.source_aggregator import collect_all_citations
    params = set(inspect.signature(collect_all_citations).parameters)
    for expected in ("patent_landscape", "funding_intel", "aggregated_sources",
                     "regulatory_precedent", "competitive_intelligence"):
        assert expected in params, f"collect_all_citations lost the {expected} parameter"

    src = ALIGNMENT.read_text()
    call_start = src.index("collect_all_citations(\n")
    call_body = src[call_start:call_start + 600]
    for kwarg in ("patent_landscape=", "funding_intel=", "aggregated_sources=",
                  "regulatory_precedent=", "competitive_intelligence="):
        assert kwarg in call_body, f"alignment_service stopped passing {kwarg}"


def test_competitive_intelligence_uses_matching_schema():
    """
    Block 12 reads competitor_trials.trials / fda_precedents.approvals — the
    gather_competitive_intelligence() schema. Passing the fda_pipeline result
    (fda_recent_actions / trial_pipeline) instead yields zero citations.
    """
    src = ALIGNMENT.read_text()
    call_start = src.index("collect_all_citations(\n")
    call_body = src[call_start:call_start + 600]
    assert "competitive_intelligence=_strategic_intel_for_bib" in call_body, (
        "competitive_intelligence must receive _strategic_intel_for_bib "
        "(gather_competitive_intelligence schema), not the fda_pipeline result"
    )
