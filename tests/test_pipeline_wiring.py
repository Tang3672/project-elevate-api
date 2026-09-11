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


# ─────────────────────────────────────────────────────────────────────────────
# Generic double-write guard
#
# The report.sources bug (collect_all_citations() built the bibliography, then
# build_sources_from_report() silently discarded it) is an instance of a class:
# one code path computes rich data into a report field, a later path replaces it,
# and nothing raises. Rather than test the known instances one at a time, this
# guard flags EVERY report.<field> written from more than one place and requires
# each to carry a written justification.
#
# If this test fails, a new double-write was introduced. Determine whether the
# later write discards the earlier one. If it is safe (mutually exclusive
# branches, or a deliberate merge), add it to REVIEWED_DOUBLE_WRITES with the
# reason. If it is not safe, fix it — do not just add the key.
# ─────────────────────────────────────────────────────────────────────────────

REVIEWED_DOUBLE_WRITES = {
    "sources":
        "MERGED. _generate_expert_report builds the full pipeline bibliography via "
        "collect_all_citations(); generate_pi_report re-appends what "
        "build_sources_from_report() drops. See the bibliography wiring tests above.",
    "validation":
        "SAFE. Mutually exclusive: the skip_verification branch writes a PENDING "
        "placeholder, the else branch delegates to run_report_verification().",
    "trust":
        "SAFE. Mutually exclusive, same skip_verification if/else as report.validation.",
    "archetype_violations":
        "SAFE. Mutually exclusive if/else (violations found vs empty list).",
    "competitive_landscape":
        "SAFE. Research-tool branch returns early; the remaining writes are the "
        "main path and its except handler.",
    "axis_decisions":
        "INTENTIONAL OVERRIDE. _generate_expert_report's A.2 block computes lifts "
        "from the segmentation tree's dimension_report; generate_pi_report then "
        "replaces it with the axis-library selection plus idea-derived lift hints. "
        "The library path wins on purpose: it yields the full axis set with "
        "non-candidate rejection reasons, and the two taxonomies use different "
        "axis_ids so they cannot be merged. A.2 survives only if the library step "
        "raises. Do not silently flip this precedence.",
    "sensitivity":
        "DOMAIN-DEPENDENT OVERRIDE. Monte Carlo sensitivity_ranking is written "
        "first; for LIFE_SCIENCES_RESEARCH the segment-tree tornado analysis "
        "(spec D.7) replaces it. The two payloads share no keys — see "
        "test_sensitivity_payload_shapes_are_documented.",
}


def _report_field_writes():
    """Map report.<field> -> [(lineno, enclosing function), ...] for alignment_service."""
    tree = ast.parse(ALIGNMENT.read_text())
    funcs = [
        (n.lineno, getattr(n, "end_lineno", n.lineno), n.name)
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    def enclosing(line):
        best = None
        for start, end, name in funcs:
            if start <= line <= end and (best is None or start > best[0]):
                best = (start, end, name)
        return best[2] if best else "<module>"

    writes: dict[str, list] = {}
    for node in ast.walk(tree):
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
            targets = [node.target]
        for t in targets:
            if (isinstance(t, ast.Attribute)
                    and isinstance(t.value, ast.Name)
                    and t.value.id == "report"):
                writes.setdefault(t.attr, []).append((node.lineno, enclosing(node.lineno)))
    return writes


def test_every_report_field_double_write_is_reviewed():
    """Any report field written from 2+ places must carry a justification."""
    multi = {f: locs for f, locs in _report_field_writes().items() if len(locs) > 1}
    unreviewed = sorted(set(multi) - set(REVIEWED_DOUBLE_WRITES))
    detail = "\n".join(
        f"  report.{f}: " + ", ".join(f"line {ln} in {fn}" for ln, fn in sorted(multi[f]))
        for f in unreviewed
    )
    assert not unreviewed, (
        "New report field(s) written from more than one place:\n" + detail +
        "\n\nCheck whether the later write discards the earlier one. This is how the "
        "report.sources bibliography bug shipped. If safe, add the field to "
        "REVIEWED_DOUBLE_WRITES with the reason; if not, fix the ordering."
    )


def test_reviewed_double_writes_list_has_no_stale_entries():
    """Keep the justification list honest — drop entries that no longer double-write."""
    multi = {f for f, locs in _report_field_writes().items() if len(locs) > 1}
    stale = sorted(set(REVIEWED_DOUBLE_WRITES) - multi)
    assert not stale, (
        f"REVIEWED_DOUBLE_WRITES lists field(s) that are no longer written twice: "
        f"{stale}. Remove them so the list keeps reflecting reality."
    )


def test_sensitivity_payload_shapes_are_documented():
    """
    report.sensitivity receives two payloads with NO keys in common:
      Monte Carlo  -> parameter, lo_label, hi_label, som_at_lo, som_at_hi, swing_pct
      segment tree -> node_id, label, method, impact_usd, impact_pct, ...
    Any consumer must handle both. If a field is renamed so the shapes start to
    overlap (or diverge further), this test fails and the consumer needs review.
    """
    from dataclasses import fields as dc_fields
    from app.services.market_sizing_derivation_service import SensitivityEntry

    mc_keys = {f.name for f in dc_fields(SensitivityEntry)}
    assert mc_keys == {"parameter", "lo_label", "hi_label",
                       "som_at_lo", "som_at_hi", "swing_pct"}, (
        f"SensitivityEntry shape changed to {sorted(mc_keys)} — report.sensitivity "
        "consumers assume the documented Monte Carlo shape"
    )

    seg_keys = {"node_id", "label", "method", "base_value", "base_frac",
                "low_frac", "high_frac", "tam_base_usd", "tam_low_usd",
                "tam_high_usd", "impact_usd", "impact_pct"}
    assert not (mc_keys & seg_keys), (
        "The two report.sensitivity payloads now share keys "
        f"({sorted(mc_keys & seg_keys)}). Consumers distinguish them structurally; "
        "overlapping keys make that ambiguous."
    )


def test_report_field_failures_are_not_logged_below_warning():
    """
    A try block that populates a user-visible report field must not hide its
    failure at debug level. Railway logs INFO and above, so a debug-only handler
    makes a whole missing report section invisible in production — the same
    class of silent failure as the discarded bibliography.

    alignment_service already logs every other non-fatal failure at warning;
    this keeps that convention enforced.
    """
    tree = ast.parse(ALIGNMENT.read_text())
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        fields = {
            t.attr
            for c in ast.walk(node) if isinstance(c, ast.Assign)
            for t in c.targets
            if isinstance(t, ast.Attribute)
            and isinstance(t.value, ast.Name) and t.value.id == "report"
        }
        if not fields:
            continue
        for handler in node.handlers:
            if len(handler.body) == 1 and isinstance(handler.body[0], ast.Pass):
                offenders.append((handler.lineno, sorted(fields), "except: pass"))
                continue
            levels = {
                c.func.attr
                for c in ast.walk(handler) if isinstance(c, ast.Call)
                if isinstance(c.func, ast.Attribute)
                and c.func.attr in {"debug", "info", "warning", "error",
                                    "exception", "critical"}
            }
            if levels and levels <= {"debug"}:
                offenders.append((handler.lineno, sorted(fields), "debug-only log"))

    detail = "\n".join(
        f"  line {ln}: {why} while writing report.{', report.'.join(f)}"
        for ln, f, why in sorted(offenders)
    )
    assert not offenders, (
        "Exception handler(s) hide a report-field failure below warning level:\n"
        + detail
        + "\n\nUse logger.warning so a missing report section is visible in production."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Report-content regressions found by auditing a shipped report
# ─────────────────────────────────────────────────────────────────────────────

def test_stale_date_scrub_preserves_citation_years():
    """
    The R-04 stale-date scrubber replaces past dates in recommended_next_steps so
    the action plan never shows an expired deadline. It must not strip publication
    years out of citations — a shipped report read
    "following the 10x Genomics/Zheng et al. (Science [date removed]) precedent".
    """
    import re
    from datetime import datetime, timezone

    src = ALIGNMENT.read_text()
    assert "_CITATION_CUE_RE" in src, (
        "the citation-year exemption was removed from the R-04 scrubber — "
        "past publication years will be replaced with [date removed]"
    )

    # Re-run the scrubber's own logic over citation vs milestone text.
    now = datetime.now(timezone.utc)
    year_re = re.compile(r"\b(20\d{2})\b")
    cue_re = re.compile(
        r"(?:et\s+al\.?,?\s*\(?|"
        r"PMID:?\s*\d*\s*|doi:?\s*\S*\s*|"
        r"\b(?:Science|Nature|Cell|Lancet|NEJM|JAMA|PNAS|BMJ|eLife|Neuron|"
        r"Nat\s+\w+|Sci\s+\w+|J\s+\w+|PLOS\s+\w+|Proc\s+\w+)"
        r"\s*,?\s*\(?)$",
        re.I,
    )

    def scrub(text):
        def rep(m):
            if int(m.group(1)) >= now.year:
                return m.group(0)
            if cue_re.search(text[max(0, m.start() - 45):m.start()]):
                return m.group(0)
            return "[date removed]"
        return year_re.sub(rep, text)

    citations = [
        "following the 10x Genomics/Zheng et al. (Science 2017) precedent",
        "Open Ephys started as lab hardware at MIT (Siegle et al., Nat Neurosci 2017).",
        "manual retrieval (Lopes et al. 2015; Hu et al. 2014)",
    ]
    for text in citations:
        assert "[date removed]" not in scrub(text), f"citation year stripped from: {text}"

    milestones = [
        "Submit the SBIR Phase I application by the 2024 deadline.",
        "Complete the pilot deployment in 2023 before fundraising.",
    ]
    for text in milestones:
        assert "[date removed]" in scrub(text), f"stale milestone survived: {text}"


def test_computed_axis_lifts_reach_the_report():
    """
    A.2 requires alignment_service to override axis_decisions with lifts computed
    from real between-group variance for LIFE_SCIENCES_RESEARCH. generate_pi_report
    previously replaced that wholesale with the axis-library heuristic, so no
    computed lift ever reached the user.
    """
    src = ALIGNMENT.read_text()
    assert "_library_axes" in src, "C.2 no longer keeps the library result separate"
    lib_line = src.index("_library_axes = format_axis_decisions")
    guard = src.index('if _computed.get("selected"):')
    assert lib_line < guard, "the computed-lift guard must follow the library selection"
    assert '"selected": _computed["selected"]' in src, (
        "generate_pi_report no longer prefers A.2's computed lifts — the axis-library "
        "heuristic will overwrite measured variance again"
    )


def test_market_percentages_use_consistent_precision():
    """
    The canonical formula line and the derivation step assumptions print the same
    ratios. A shipped report showed 'SOM = SAM x 22.5%' next to 'midpoint 22%'.
    Both sides now use :g so 60.0 renders '60' and 0.225 renders '22.5'.
    """
    deriv = (ROOT / "app" / "services" / "market_sizing_derivation_service.py").read_text()
    assert "{som_mid*100:g}%" in deriv, "SOM midpoint reverted to .0% rounding"
    assert "{sam_mid*100:g}%" in deriv, "SAM midpoint reverted to .0% rounding"
    assert "{som_mid:.0%}" not in deriv, "SOM midpoint still uses .0% somewhere"

    src = ALIGNMENT.read_text()
    assert "{pen:g}%" in src and "{cap:g}%" in src, (
        "the canonical formula line no longer uses :g — it will disagree with the "
        "derivation steps again (22.5% vs 22%)"
    )
