"""
B-05 — Competitor schema per archetype; ban "undefined" in rendered output
==========================================================================
Two failure modes this spec item guards against:

  1. Schema mismatch: a research-tool comparator entry being rendered by the
     drug/device template (or vice versa) exposes fields like `company` or
     `stage` that don't exist in the research-tool schema — JavaScript renders
     `undefined` for missing fields unless they are explicitly guarded.

  2. "undefined" in rendered output: any field access on a competitor dict that
     is `None` or missing must fall back to "" in both the server-side PDF
     renderer (_e) and the client-side JS template literals.

Tests verify:
  - COMPETITOR_SCHEMA covers research-tool and drug archetypes with distinct
    required / forbidden field sets.
  - Static _RESEARCH_TOOL_COMPARATORS entries satisfy the research-tool schema.
  - validate_competitor_entry() correctly flags violations.
  - PDF renderer never emits "undefined" when competitor entries have absent
    optional fields (drug schema, research-tool schema, mixed-schema inputs).
  - The `_e()` helper turns None → "".
  - Frontend JS template guards (c.name||'', c.company||'') are present for
    the drug competitor card.

All backend tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import re

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _archetype(value: str):
    from app.services.product_archetype import ProductArchetype
    return ProductArchetype(value)


def _schema(archetype_value: str) -> dict:
    from app.services.product_archetype import get_competitor_schema, ProductArchetype
    return get_competitor_schema(ProductArchetype(archetype_value))


def _validate(entry: dict, archetype_value: str) -> list[str]:
    from app.services.product_archetype import validate_competitor_entry, ProductArchetype
    return validate_competitor_entry(entry, ProductArchetype(archetype_value))


# Minimal valid research-tool comparator entry
_RT_ENTRY = {
    "name":        "ActiGraph GT9X Link",
    "category":    "Commercial research wearable logger",
    "description": "Industry-standard motion sensor for NIH-funded trials.",
    "url":         "https://actigraphcorp.com",
    "incumbent":   True,
}

# Minimal valid drug competitor entry
_DRUG_ENTRY = {
    "name":    "Omadacycline",
    "company": "Paratek Pharmaceuticals",
    "stage":   "approved",
}

# Drug entry with all optional fields
_DRUG_ENTRY_FULL = {
    "name":              "Ceftazidime-avibactam",
    "company":           "AstraZeneca / Pfizer",
    "stage":             "approved",
    "brand_name":        "Avycaz",
    "route":             "IV",
    "advantages":        ["BLI spectrum", "QIDP exclusivity"],
    "vulnerabilities":   ["IV-only limits outpatient use"],
    "positioning_signal": "First BLI combination against MBL-producing organisms.",
}


# ══════════════════════════════════════════════════════════════════════════════
# Schema definitions
# ══════════════════════════════════════════════════════════════════════════════

class TestCompetitorSchemaDefinitions:

    def test_research_tool_schema_exists(self):
        schema = _schema("research_tool_non_clinical")
        assert schema, "COMPETITOR_SCHEMA must have an entry for research_tool_non_clinical"
        assert schema["required_fields"], "required_fields must be non-empty"
        assert schema["forbidden_fields"], "forbidden_fields must be non-empty"

    def test_research_tool_required_fields(self):
        schema = _schema("research_tool_non_clinical")
        assert "name" in schema["required_fields"]
        assert "category" in schema["required_fields"]
        assert "description" in schema["required_fields"]

    def test_research_tool_forbids_drug_fields(self):
        schema = _schema("research_tool_non_clinical")
        for field in ("stage", "nct_id", "sponsor", "company"):
            assert field in schema["forbidden_fields"], (
                f"research_tool schema must forbid drug field {field!r}"
            )

    def test_drug_schema_exists(self):
        schema = _schema("therapeutic_small_molecule")
        assert "name" in schema["required_fields"]
        assert "company" in schema["required_fields"]
        assert "stage" in schema["required_fields"]

    def test_drug_schema_forbids_research_tool_fields(self):
        schema = _schema("therapeutic_small_molecule")
        for field in ("incumbent", "url", "category"):
            assert field in schema["forbidden_fields"], (
                f"drug schema must forbid research-tool field {field!r}"
            )

    def test_device_schema_exists(self):
        schema = _schema("device_class_ii")
        assert "name" in schema["required_fields"]
        assert "company" in schema["required_fields"]
        assert "stage" in schema["required_fields"]

    def test_samd_schema_exists(self):
        schema = _schema("samd_clinical")
        assert "name" in schema["required_fields"]

    def test_research_infra_schema_exists(self):
        schema = _schema("research_infrastructure_saas")
        assert "name" in schema["required_fields"]
        assert "description" in schema["required_fields"]

    def test_unknown_archetype_returns_fallback(self):
        from app.services.product_archetype import get_competitor_schema, ProductArchetype
        schema = get_competitor_schema(ProductArchetype.UNKNOWN)
        assert "required_fields" in schema
        assert "forbidden_fields" in schema


# ══════════════════════════════════════════════════════════════════════════════
# validate_competitor_entry
# ══════════════════════════════════════════════════════════════════════════════

class TestValidateCompetitorEntry:

    def test_valid_research_tool_entry_passes(self):
        assert _validate(_RT_ENTRY, "research_tool_non_clinical") == []

    def test_valid_drug_entry_passes(self):
        assert _validate(_DRUG_ENTRY, "therapeutic_small_molecule") == []

    def test_valid_full_drug_entry_passes(self):
        assert _validate(_DRUG_ENTRY_FULL, "therapeutic_small_molecule") == []

    def test_research_tool_entry_missing_name_fails(self):
        entry = {**_RT_ENTRY, "name": ""}
        violations = _validate(entry, "research_tool_non_clinical")
        assert violations, "Missing 'name' must be flagged"
        assert any("name" in v for v in violations)

    def test_research_tool_entry_missing_description_fails(self):
        entry = {k: v for k, v in _RT_ENTRY.items() if k != "description"}
        violations = _validate(entry, "research_tool_non_clinical")
        assert violations
        assert any("description" in v for v in violations)

    def test_drug_entry_missing_company_fails(self):
        entry = {k: v for k, v in _DRUG_ENTRY.items() if k != "company"}
        violations = _validate(entry, "therapeutic_small_molecule")
        assert violations
        assert any("company" in v for v in violations)

    def test_drug_entry_missing_stage_fails(self):
        entry = {k: v for k, v in _DRUG_ENTRY.items() if k != "stage"}
        violations = _validate(entry, "therapeutic_small_molecule")
        assert violations
        assert any("stage" in v for v in violations)

    def test_research_tool_entry_with_stage_fails(self):
        """research-tool schema forbids 'stage' — using a drug field signals mismatch."""
        entry = {**_RT_ENTRY, "stage": "approved"}
        violations = _validate(entry, "research_tool_non_clinical")
        assert violations
        assert any("stage" in v for v in violations)

    def test_research_tool_entry_with_nct_id_fails(self):
        entry = {**_RT_ENTRY, "nct_id": "NCT12345678"}
        violations = _validate(entry, "research_tool_non_clinical")
        assert violations
        assert any("nct_id" in v for v in violations)

    def test_drug_entry_with_incumbent_fails(self):
        """'incumbent' is a research-tool field — must not appear in drug entries."""
        entry = {**_DRUG_ENTRY, "incumbent": True}
        violations = _validate(entry, "therapeutic_small_molecule")
        assert violations
        assert any("incumbent" in v for v in violations)


# ══════════════════════════════════════════════════════════════════════════════
# Static _RESEARCH_TOOL_COMPARATORS satisfy the schema
# ══════════════════════════════════════════════════════════════════════════════

class TestStaticComparatorsSatisfySchema:

    def test_all_research_tool_comparators_pass_schema(self):
        from app.services.competitive_intelligence_service import _RESEARCH_TOOL_COMPARATORS
        violations: list[str] = []
        for entry in _RESEARCH_TOOL_COMPARATORS:
            violations.extend(_validate(entry, "research_tool_non_clinical"))
        assert not violations, (
            "Static _RESEARCH_TOOL_COMPARATORS have schema violations:\n"
            + "\n".join(violations)
        )

    def test_research_tool_comparators_have_no_stage_field(self):
        from app.services.competitive_intelligence_service import _RESEARCH_TOOL_COMPARATORS
        bad = [c for c in _RESEARCH_TOOL_COMPARATORS if "stage" in c]
        assert not bad, (
            f"_RESEARCH_TOOL_COMPARATORS entries must not have 'stage' field: {bad!r}"
        )

    def test_research_tool_comparators_have_no_company_field(self):
        from app.services.competitive_intelligence_service import _RESEARCH_TOOL_COMPARATORS
        bad = [c for c in _RESEARCH_TOOL_COMPARATORS if "company" in c]
        assert not bad, (
            f"_RESEARCH_TOOL_COMPARATORS entries must not have 'company' field: {bad!r}"
        )

    def test_research_tool_comparators_all_have_name(self):
        from app.services.competitive_intelligence_service import _RESEARCH_TOOL_COMPARATORS
        for entry in _RESEARCH_TOOL_COMPARATORS:
            assert entry.get("name"), f"All comparators must have a name: {entry!r}"

    def test_status_quo_is_present(self):
        """Status quo / DIY must always be in the research-tool list (B-07 competitor rule)."""
        from app.services.competitive_intelligence_service import _RESEARCH_TOOL_COMPARATORS
        names = " ".join(c.get("name", "").lower() for c in _RESEARCH_TOOL_COMPARATORS)
        assert "diy" in names or "status quo" in names or "sd card" in names or "sd-card" in names, (
            "Status-quo / DIY must be included as a first-class comparator in "
            "_RESEARCH_TOOL_COMPARATORS"
        )


# ══════════════════════════════════════════════════════════════════════════════
# PDF renderer — no "undefined" with sparse entries
# ══════════════════════════════════════════════════════════════════════════════

def _strip_tags(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html)


class TestPdfRendererNoUndefined:

    def _render_ci(self, ci: dict) -> str:
        from app.services.pdf_renderer import _render_competitive_landscape
        return _render_competitive_landscape(ci)

    def test_research_tool_comparators_no_undefined(self):
        """Research-tool comparators render without 'undefined'."""
        ci = {
            "research_tool_comparators": [
                {"name": "ActiGraph", "category": "Wearable logger",
                 "description": "Standard research wearable.", "incumbent": True},
                {"name": "DIY Scripts", "category": "Status quo",
                 "description": "Manual scripts + SD cards.", "incumbent": True},
            ]
        }
        html = self._render_ci(ci)
        assert "undefined" not in _strip_tags(html).lower()

    def test_research_tool_comparator_missing_optional_fields_no_undefined(self):
        """Missing optional fields (url, incumbent) must not produce 'undefined'."""
        ci = {
            "research_tool_comparators": [
                {"name": "Bare entry", "category": "Research tool",
                 "description": "No url, no incumbent."},
            ]
        }
        html = self._render_ci(ci)
        assert "undefined" not in _strip_tags(html).lower()

    def test_empty_ci_returns_empty_string(self):
        assert self._render_ci({}) == ""
        assert self._render_ci(None) == ""

    def test_none_fields_in_comparator_no_undefined(self):
        """None values in all comparator fields must not produce 'undefined' or 'None'."""
        ci = {
            "research_tool_comparators": [
                {"name": None, "category": None, "description": None,
                 "url": None, "incumbent": None},
            ]
        }
        html = self._render_ci(ci)
        text = _strip_tags(html).lower()
        assert "undefined" not in text
        assert "none" not in text

    def test_honest_empty_state_renders(self):
        ci = {
            "honest_empty_state": "No comparators found — manual research required.",
            "research_tool_comparators": [],
        }
        html = self._render_ci(ci)
        assert "No comparators found" in html

    def test_clinical_trials_path_no_undefined(self):
        """Drug/device competitor_trials path must also not produce 'undefined'."""
        ci = {
            "competitor_trials": {
                "trials": [
                    {"nct_id": "NCT12345678", "title": "Phase 3 AMR trial",
                     "status": "Recruiting", "sponsor": "Paratek"},
                    {"nct_id": "NCT87654321", "title": None,
                     "status": None, "sponsor": None},
                ]
            }
        }
        html = self._render_ci(ci)
        assert "undefined" not in _strip_tags(html).lower()


# ══════════════════════════════════════════════════════════════════════════════
# _e() helper — None and absent values become ""
# ══════════════════════════════════════════════════════════════════════════════

class TestEscapeHelper:

    def test_none_becomes_empty(self):
        from app.services.pdf_renderer import _e
        assert _e(None) == ""

    def test_empty_string_stays_empty(self):
        from app.services.pdf_renderer import _e
        assert _e("") == ""

    def test_normal_string_passes_through(self):
        from app.services.pdf_renderer import _e
        assert _e("ActiGraph") == "ActiGraph"

    def test_html_entities_escaped(self):
        from app.services.pdf_renderer import _e
        result = _e("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;" in result


# ══════════════════════════════════════════════════════════════════════════════
# Frontend JS: c.name and c.company must be guarded in drug competitor template
# ══════════════════════════════════════════════════════════════════════════════

class TestFrontendUndefinedGuards:
    """
    The drug competitor card template in app.html must not use bare ${c.name}
    or ${c.company} — both must have a ||'' fallback to prevent "undefined".
    """

    def _competitor_card_block(self) -> str:
        import os
        path = os.path.join(
            os.path.dirname(__file__), "..",
            "..", "ProjectElevate-Frontend", "app.html",
        )
        path = os.path.normpath(path)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        # Extract the drug competitor forEach block
        m = re.search(
            r"data\.competitors\.slice\(0,8\)\.forEach\(c => \{(.*?)\}\);",
            src, re.DOTALL,
        )
        assert m, "Could not find drug competitor forEach block in app.html"
        return m.group(1)

    def test_c_name_has_fallback(self):
        block = self._competitor_card_block()
        # Must not have bare ${c.name} without || fallback
        bare = re.findall(r'\$\{c\.name\}(?!\s*\|)', block)
        assert not bare, (
            "Drug competitor card has bare ${c.name} without ||'' fallback — "
            "renders 'undefined' when name is missing. Found: " + str(bare)
        )

    def test_c_company_has_fallback(self):
        block = self._competitor_card_block()
        bare = re.findall(r'\$\{c\.company\}(?!\s*\|)', block)
        assert not bare, (
            "Drug competitor card has bare ${c.company} without ||'' fallback — "
            "renders 'undefined' when company is missing. Found: " + str(bare)
        )

    def test_stage_label_has_fallback(self):
        block = self._competitor_card_block()
        # stageLabel[c.stage] must have a fallback — either via stageLbl variable
        # or directly || ''
        has_stage_label_fallback = (
            "stageLbl" in block or
            re.search(r'stageLabel\[c\.stage\]\s*\|\|', block) is not None
        )
        assert has_stage_label_fallback, (
            "Drug competitor card stage label must have a fallback when c.stage "
            "is undefined or unrecognised. Use a stageLbl variable or add ||'' ."
        )
