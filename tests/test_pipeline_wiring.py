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


# ─────────────────────────────────────────────────────────────────────────────
# Bibliography size floor + inline citation linkage
#
# Measured end-to-end against live fetchers for a non-clinical research-tool idea:
# 42 sources. These tests lock in the wiring that produces that number, and the
# inline [N] markers the frontend's citation linker turns into #src-N anchors.
# ─────────────────────────────────────────────────────────────────────────────

MIN_EXPECTED_SOURCES = 30


def _realistic_pipeline_payloads():
    """Payload volumes matching what the live fetchers actually return."""
    return (
        {  # funding_intel
            "sbir_awards": [
                {"project_title": f"Telemetry platform {i}", "company": f"NeuroCo{i}",
                 "fiscal_year": 2025, "url": f"https://reporter.nih.gov/project-details/108{i:05d}"}
                for i in range(8)
            ],
            "edgar_signals": [],
            "new_entrants": [],
            "preprints": {"recent_titles": [
                {"title": f"Preprint {i}", "authors": "Lee A", "server": "biorxiv",
                 "doi": f"10.1101/2026.0{i}.01", "url": f"https://doi.org/10.1101/2026.0{i}.01"}
                for i in range(4)
            ]},
        },
        {  # aggregated_sources
            "papers": [{"title": f"Paper {i}", "source": "CrossRef",
                        "url": f"https://pubmed.ncbi.nlm.nih.gov/{3000000+i}/"} for i in range(12)],
            "nih_grants": [{"title": f"Grant {i}", "project_num": f"R01NS{100+i}", "pi_name": f"Dr {i}",
                            "url": f"https://reporter.nih.gov/project-details/R01NS{100+i}"} for i in range(5)],
            "gbd": [{"title": "Neuro disorders GBD 2021", "url": "https://vizhub.healthdata.org/gbd-results/"}],
            "news": [{"title": f"Industry item {i}", "source": "STAT", "date": "2026-01-01",
                      "url": f"https://www.statnews.com/2026/01/0{i}/item"} for i in range(6)],
            "drug_shortage": [{"drug": "n/a", "url": "https://www.ashp.org/drug-shortages/current-shortages"}],
            "cms_pricing": [], "sec_filings": [],
        },
    )


def test_bibliography_clears_minimum_source_floor():
    """
    A research-tool report must ship a substantive bibliography. If this drops,
    a harvesting block stopped firing or a consumer started discarding entries.
    """
    from app.services.source_aggregator import collect_all_citations
    funding_intel, aggregated = _realistic_pipeline_payloads()
    cites = collect_all_citations(
        {"sources": [], "disease_intelligence": {"data_points": []},
         "market_sizing": {"steps": []}, "strategic_playbook": []},
        patent_landscape=None, funding_intel=funding_intel,
        aggregated_sources=aggregated, regulatory_precedent=None,
        competitive_intelligence=None,
    )
    assert len(cites) >= MIN_EXPECTED_SOURCES, (
        f"bibliography fell to {len(cites)} sources (floor {MIN_EXPECTED_SOURCES}). "
        "A harvesting block stopped firing or entries are being dropped."
    )
    assert all(c.get("url") for c in cites), "a harvested citation has no URL"
    numbers = [c["number"] for c in cites]
    assert numbers == list(range(1, len(numbers) + 1)), "citation numbering is not contiguous"


def test_industry_news_is_harvested():
    """news items carry URLs and were previously dropped on the floor."""
    from app.services.source_aggregator import collect_all_citations
    cites = collect_all_citations(
        {"sources": []},
        aggregated_sources={"news": [
            {"title": "Bruker Neuroscience Summit", "source": "Bruker", "date": "2026-01-01",
             "url": "https://www.bruker.com/news/summit-2026"}]},
    )
    assert any("bruker.com" in c.get("url", "") for c in cites), (
        "aggregated_sources.news is no longer harvested into the bibliography"
    )


def test_inline_markers_resolve_to_final_bibliography_numbers():
    """
    Claude tags claims with [SOURCE: name | url]; those must become [N] matching
    the FINAL bibliography numbering, because generate_pi_report renumbers after
    merging the pipeline sources. A marker with no URL must degrade to plain text
    rather than leave a [N] pointing at nothing.
    """
    from app.models.alignment import PIReport
    from app.services.source_formatter import apply_inline_citations

    report = PIReport(
        product_type="other",
        idea_submitted="research tool",
        executive_summary=(
            "Known source [SOURCE: Lopes 2015 | https://pubmed.ncbi.nlm.nih.gov/26834641/]. "
            "New source [SOURCE: Mystery | https://example.org/new]. "
            "No url [SOURCE: Internal estimate]."
        ),
    )
    report.recommended_next_steps = [
        "Nested field [SOURCE: NIH RePORTER | https://reporter.nih.gov/]."
    ]
    sources = [
        {"number": 1, "name": "Filler", "url": "https://example.com/filler"},
        {"number": 2, "name": "Lopes 2015", "url": "https://pubmed.ncbi.nlm.nih.gov/26834641/"},
    ]
    stats = apply_inline_citations(report, sources)

    assert "[2]" in report.executive_summary, "known URL did not resolve to its bibliography number"
    assert "[SOURCE:" not in report.executive_summary, "raw marker left in the report body"
    assert "Internal estimate" in report.executive_summary and "[3]" not in report.executive_summary.split("No url")[1], (
        "a URL-less marker produced a dangling citation number"
    )
    assert "[SOURCE:" not in report.recommended_next_steps[0], "nested list field was not walked"
    assert stats["appended"] >= 1, "a newly cited URL was not appended to the bibliography"

    numbers = {s["number"] for s in sources}
    import re as _re
    refs = {int(n) for n in _re.findall(r"\[(\d+)\]",
            report.executive_summary + " " + report.recommended_next_steps[0])}
    assert refs <= numbers, f"inline refs {sorted(refs - numbers)} have no bibliography entry"


def test_generate_pi_report_resolves_inline_citations():
    """The inline pass must run, and must run AFTER the bibliography is final."""
    src = ALIGNMENT.read_text()
    assert "apply_inline_citations" in src, (
        "generate_pi_report no longer resolves [SOURCE:] markers — the report body "
        "will keep raw markers and the frontend [N] linker will have nothing to link"
    )
    assert src.index("report.sources = _raw_sources") < src.index("apply_inline_citations(report"), (
        "inline citations must be resolved after the final bibliography is assigned, "
        "otherwise [N] numbers will not match the merged numbering"
    )


def test_prompt_does_not_forbid_the_source_marker_format():
    """
    knowledge_retriever, disease_knowledge and pubmed_service all instruct Claude to
    tag claims with [SOURCE: name | url]. alignment_service used to say "Do NOT use
    [SOURCE: x] format" in the same prompt, so the markers were never emitted and
    narrative claims contributed nothing to the bibliography.
    """
    src = ALIGNMENT.read_text()
    assert "Do NOT use [SOURCE: x] format" not in src, (
        "the citation-style instruction contradicts the [SOURCE:] tagging rules in "
        "knowledge_retriever.py / disease_knowledge.py / pubmed_service.py again"
    )


# ─────────────────────────────────────────────────────────────────────────────
# H-07 pricing reconciliation — was fully implemented, tested, and never called
# ─────────────────────────────────────────────────────────────────────────────

def test_h07_pricing_reconciliation_is_wired_into_production():
    """
    check_price_vs_spend_band() implements the reconciliation that the Step 2
    rationale promises the reader ("if the asking price exceeds the observed spend
    ceiling, this gap should appear in the reconciliation"), but it was referenced
    only by its own definition and its unit tests. A shipped report paired an
    $8,500/yr price benchmark with a $500/yr spend ceiling and said nothing.
    """
    src = ALIGNMENT.read_text()
    assert "PRICING MISMATCH" in src, (
        "the H-07 pricing reconciliation is no longer wired into alignment_service — "
        "a price/spend gap will ship unflagged again"
    )
    assert "spend_ceiling_annual_usd" in src, (
        "alignment_service no longer reads the buyer spend ceiling off the derivation"
    )


def test_derivation_exposes_spend_ceiling_reflecting_user_overrides():
    """
    The ceiling must be the PI's overridden band, not the buyer-model default.
    The default academic-lab ceiling is $10,000/yr; the Hublink intake overrode it
    to $500/yr. Using the default would make an $8,500/yr benchmark look fine.
    """
    from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
    d = generate_market_sizing_derivation(
        idea="Hublink automates SD-card-to-cloud sync for behavioral neurotech labs",
        product_type="other", disease_name="", therapeutic_area="neuroscience",
        us_patient_population=0, sub_expert_id="research_tool_non_clinical",
        user_params={"seg.target_lab_count": "30,000-80,000 qualifying labs",
                     "price.annual_per_lab": "$250-$500/yr per lab"},
    )
    ceiling = getattr(d, "spend_ceiling_annual_usd", None)
    assert ceiling == 500.0, (
        f"spend ceiling is {ceiling}, expected the PI-overridden 500.0 — if this is "
        "10000.0 the override stopped propagating and H-07 will not fire"
    )
    assert 8500 / ceiling > 1.0, "the Hublink price/spend gap no longer trips H-07"


def test_step1_rationale_has_no_double_period():
    """
    The Step 1 rationale appended '.' to a user-supplied source string that already
    ended in one, producing '...before using for fundraising..'.
    """
    from app.services.market_sizing_derivation_service import generate_market_sizing_derivation
    d = generate_market_sizing_derivation(
        idea="behavioral neurotech cloud sync", product_type="other", disease_name="",
        therapeutic_area="neuroscience", us_patient_population=0,
        sub_expert_id="research_tool_non_clinical",
        user_params={"seg.target_lab_count": "30,000-80,000 qualifying labs."},
    )
    text = getattr(d.steps[0], "rationale", "") or getattr(d.steps[0], "explanation", "")
    assert ".." not in text, f"double period in Step 1 rationale: ...{text[-70:]!r}"


def test_triangulation_divergence_compares_like_for_like():
    """
    Divergence measured bottom-up SAM against top-down TAM, so the SAM fraction was
    baked into the "disagreement": at a 60% SAM fraction two models that agree
    perfectly scored 40% divergence, above the 25% threshold, meaning the
    cross-validation could never pass for a typical research-tool funnel.
    """
    from app.services.market_sizing_triangulator import triangulate, DIVERGENCE_THRESHOLD
    kw = dict(disease_name="behavioral neuroscience",
              therapeutic_area="neuroscience", product_type="other")
    td = 157_500_000

    for sam_fraction in (0.50, 0.60, 0.75):
        r = triangulate(bottom_up_sam_usd=td * sam_fraction,
                        bottom_up_tam_usd=td, top_down_tam_usd=td, **kw)
        assert r.divergence_ratio < 1e-9, (
            f"models agreeing exactly report {r.divergence_ratio:.1%} divergence at a "
            f"{sam_fraction:.0%} SAM fraction — the funnel stage is leaking into the check"
        )
        assert not r.divergence_flagged

    # A genuine disagreement must still flag.
    r = triangulate(bottom_up_sam_usd=12_375_000, bottom_up_tam_usd=20_625_000,
                    top_down_tam_usd=td, **kw)
    assert r.divergence_flagged, "a real 87% TAM gap stopped flagging"
    assert r.divergence_ratio > DIVERGENCE_THRESHOLD


def test_derivation_passes_bottom_up_tam_to_triangulator():
    """Without this the triangulator silently falls back to the SAM-vs-TAM comparison."""
    deriv_src = (ROOT / "app" / "services" / "market_sizing_derivation_service.py").read_text()
    assert "bottom_up_tam_usd=deriv.us_tam_usd" in deriv_src, (
        "the derivation stopped passing its TAM, so divergence reverts to comparing "
        "SAM against TAM and will over-report disagreement"
    )
