"""
H-10 — Legacy branding leak lint tests.

These run in CI against the source tree, not against generated reports.
They catch the specific pattern: internal knowledge-base labels being used
as user-facing citation sources in system prompts or seed knowledge.

What is tested:
  1. No prompt/knowledge file emits "Project Elevate RPM Context" or similar
     combined internal labels as a citable source string.
  2. No system prompt instructs the model to cite "every" claim without
     the caveat that source names must be real external publications.
  3. The INTERNAL_KB_PATTERNS in citation_validator covers the known offenders.
  4. The reporting instruction in alignment_service explicitly bans the pattern.

What is NOT tested (intentional exclusions):
  - "Project Elevate" as a product name in email templates / UI strings —
    that's legitimate branding and not the defect.
  - "Project Elevate" in documentation / README — not user-facing report output.
"""

import ast
import re
import os
import pytest

# Root of the Python source tree
_APP_ROOT = os.path.join(os.path.dirname(__file__), "..", "app")

# Patterns that should never appear as source names in generated output.
# These live in citation_validator.INTERNAL_KB_PATTERNS but are re-asserted
# here so the lint catches them even if the validator is bypassed.
_BANNED_SOURCE_PATTERNS = [
    r"expert domain knowledge",
    r"rpm (expert |)context",
    r"medlevate rpm context",
    r"project elevate (rpm|context|knowledge)",
    r"sub.expert context",
    r"elevate context",
]

# Files where "Project Elevate" as a product name is expected and fine
_ALLOWED_FILES = {
    "email_service.py",
    "email_verification.py",
    "weekly_tracker.py",
    "pi_memory_service.py",
}


def _py_files_under(root: str):
    for dirpath, _, filenames in os.walk(root):
        if ".venv" in dirpath or "__pycache__" in dirpath:
            continue
        for fn in filenames:
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def _file_text(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except Exception:
        return ""


# ── Test 1: INTERNAL_KB_PATTERNS covers the known offenders ──────────────────

class TestInternalKBPatternsCompleteness:

    def test_medlevate_rpm_context_is_covered(self):
        from app.services.citation_validator import INTERNAL_KB_PATTERNS
        assert any("medlevate" in p or "rpm context" in p for p in INTERNAL_KB_PATTERNS)

    def test_project_elevate_is_covered(self):
        from app.services.citation_validator import INTERNAL_KB_PATTERNS
        assert any("project elevate" in p or "elevate" in p for p in INTERNAL_KB_PATTERNS)

    def test_expert_domain_knowledge_is_covered(self):
        from app.services.citation_validator import INTERNAL_KB_PATTERNS
        assert any("expert domain knowledge" in p or "domain knowledge" in p for p in INTERNAL_KB_PATTERNS)

    def test_sub_expert_context_is_covered(self):
        from app.services.citation_validator import INTERNAL_KB_PATTERNS
        assert any("sub" in p and "expert" in p or "context" in p for p in INTERNAL_KB_PATTERNS)


# ── Test 2: reporting instruction in alignment_service bans the pattern ───────

class TestAlignmentServiceReportingInstruction:

    def test_alignment_service_bans_expert_domain_knowledge_as_source(self):
        path = os.path.join(_APP_ROOT, "services", "alignment_service.py")
        text = _file_text(path)
        # The reporting rules must explicitly call out the banned source-name pattern
        assert "Expert Domain Knowledge" in text or "expert domain knowledge" in text.lower(), \
            "alignment_service.py should name 'Expert Domain Knowledge' as a banned source label"

    def test_alignment_service_bans_project_elevate_as_source(self):
        path = os.path.join(_APP_ROOT, "services", "alignment_service.py")
        text = _file_text(path)
        assert "Project Elevate" in text, \
            "alignment_service.py must call out 'Project Elevate' as a banned source label in reporting rules"

    def test_knowledge_retriever_does_not_say_every_claim(self):
        path = os.path.join(_APP_ROOT, "services", "knowledge_retriever.py")
        text = _file_text(path).lower()
        # The old instruction "Every statistic and claim MUST be tagged" is gone
        assert "every statistic and claim in your report must be tagged" not in text, \
            "knowledge_retriever.py must not instruct the model to tag every claim (encourages fabrication)"

    def test_knowledge_retriever_bans_internal_labels(self):
        path = os.path.join(_APP_ROOT, "services", "knowledge_retriever.py")
        text = _file_text(path)
        assert "Expert Domain Knowledge" in text or "Medlevate Context" in text or "Project Elevate" in text, \
            "knowledge_retriever.py must explicitly name banned internal source labels"


# ── Test 3: no system prompt embeds an internal KB reference as a citable source ──

# The dangerous pattern is the *compound* fabricated source-name format:
# "X Expert Domain Knowledge - Y Context YYYY"
# Individual keywords appearing in ban statements are acceptable; this compound
# form appearing in a prompt body is not (the LLM will echo it verbatim).
_COMPOUND_SOURCE_PATTERNS = [
    r"expert domain knowledge\s*[-–]\s*\w+",           # "RPM Expert Domain Knowledge - Medlevate..."
    r"(medlevate|project elevate)\s+rpm\s+context",    # "Medlevate RPM Context 2024"
    r"(project elevate|elevate)\s+context\s+20\d\d",   # "Elevate Context 2024"
]


class TestNoInternalKBInSystemPrompts:
    """
    System prompt files must not contain the compound fabricated source-name format
    ('X Expert Domain Knowledge - Y Context YYYY') because the LLM echoes those
    exact strings into generated citations. Individual keyword mentions in ban
    statements are fine.
    """

    @pytest.mark.parametrize("fname", [
        "expert_profiles.py",
        "expert_profiles_v2.py",
        "alignment_service.py",
        "knowledge_retriever.py",
    ])
    def test_no_compound_fabricated_source_in_prompt_files(self, fname):
        path = os.path.join(_APP_ROOT, "services", fname)
        if not os.path.exists(path):
            pytest.skip(f"{fname} not found")
        text = _file_text(path)
        hits = []
        for pat in _COMPOUND_SOURCE_PATTERNS:
            for m in re.finditer(pat, text, re.I):
                hits.append(m.group(0))
        assert hits == [], \
            f"{fname} contains compound fabricated source-name pattern(s): {hits}. " \
            "These strings get echoed verbatim into generated citations."


# ── Test 4: the banner strings are not injected as source names in the JSON schema ──

class TestExpertJsonSchemaNoBrandedSources:

    def test_json_schema_does_not_hardcode_internal_source_names(self):
        path = os.path.join(_APP_ROOT, "services", "alignment_service.py")
        text = _file_text(path)
        # The schema may describe the source field but must not give a branded example
        for pat in _BANNED_SOURCE_PATTERNS:
            hits = re.findall(pat, text, re.I)
            # One allowed occurrence per pattern: the reporting-rule ban that names the string.
            # More than 1 means it leaked into the schema or prompt body.
            assert len(hits) <= 1, \
                f"alignment_service.py: '{pat}' appears {len(hits)} times (expected ≤1 — the ban mention)"
