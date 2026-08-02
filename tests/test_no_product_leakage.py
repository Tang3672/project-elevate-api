"""
Rule 6 — Automated product-leakage test (Spec v3 Addendum).

Engine code under app/ must not contain product- or fixture-specific strings.
These identifiers may appear only in:
  - tests/  (fixture definitions, regression data)
  - stored assumption-set files
  - comments explaining bug history (# lines)

Context: Specs v1–v3 use specific product examples as regression fixtures.
The defect this test catches is fixture-specific values (prices, agency lists,
competitor names, PI names) drifting into engine code and becoming silent
defaults that apply to every product.

Allowed exceptions (documented below) cover real external entities that are
legitimately referenced by the engine for multiple products, not just one fixture.
"""

from __future__ import annotations

import ast
import os
import re

import pytest

# ── Strings that must NOT appear in engine code ───────────────────────────────
# These are identifiers that belong in tests/fixtures/ or assumption sets only.
PRODUCT_SPECIFIC_STRINGS: list[str] = [
    "Gaidica",           # PI primary research — goes in assumption sets, not engine
    "Neurotech Hub",     # Institution name from regression fixture
    "REDCap",            # Named competitor from regression fixture
    "LabKey",            # Named competitor from regression fixture
    "Synology",          # Named competitor from regression fixture
    "actigraphy",        # Product-category keyword used as competitor descriptor
]

# Strings present in engine code for LEGITIMATE domain reasons.
# Documented so future contributors understand why they are excluded.
_ALLOWED_STRINGS: set[str] = {
    # "Hublink" — excluded from above list because it appears in code comments
    #   explaining the H-07/B-07 bug history. Engine does not use it as a value.
    # "WashU" — appears alongside MIT/Harvard/Stanford as a real research university
    #   in innovation_intelligence_service.py; not Hublink-specific.
    # "Osage" — Osage University Partners is a real VC fund in investor_matcher.py.
    # "NINDS" — the NIH Institute of Neurological Disorders; correct funding agency
    #   for CNS products in dynamic_prompt_generator.py and knowledge_retriever.py.
    # "SD-card", "SD card" — not found in engine code.
    # "Project Elevate" — permitted in email_service.py, email_verification.py,
    #   weekly_tracker.py, pi_memory_service.py (branding, not engine logic).
}

# Files where product-specific names are expected and acceptable
_ALLOWED_FILE_BASENAMES: frozenset[str] = frozenset({
    "email_service.py",
    "email_verification.py",
    "weekly_tracker.py",
    "pi_memory_service.py",
})

# Directories to scan (relative to repo root)
_SCAN_DIRS: list[str] = [
    "app/services",
    "app/models",
    "app/api",
    "app/data",
    "app/db",
]

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


def _iter_py_files(scan_dir: str):
    """Yield (path, rel_path) for every .py under scan_dir, skipping __pycache__."""
    for dirpath, _, filenames in os.walk(os.path.join(_REPO_ROOT, scan_dir)):
        if "__pycache__" in dirpath:
            continue
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            if fn in _ALLOWED_FILE_BASENAMES:
                continue
            yield os.path.join(dirpath, fn), os.path.relpath(
                os.path.join(dirpath, fn), _REPO_ROOT
            )


def _strip_comments(source: str) -> str:
    """Remove # comments and triple-quoted docstrings from Python source.

    We scan only executable string literals and identifiers — bug-history
    comments that name a regression fixture are acceptable documentation.
    """
    # Remove triple-quoted docstrings (both ''' and \"\"\")
    source = re.sub(r'""".*?"""', '""""""', source, flags=re.DOTALL)
    source = re.sub(r"'''.*?'''", "''''''", source, flags=re.DOTALL)
    # Remove single-line # comments
    source = re.sub(r"#[^\n]*", "", source)
    return source


# ── Test 1: no product-specific strings in executable engine code ─────────────

@pytest.mark.parametrize("leak_str", PRODUCT_SPECIFIC_STRINGS)
def test_string_not_in_engine_executable_code(leak_str: str):
    """
    Each PRODUCT_SPECIFIC_STRINGS entry must not appear in engine executable code.
    Comments and docstrings are stripped first — bug-history notes are OK.
    """
    violations: list[str] = []
    for scan_dir in _SCAN_DIRS:
        for fpath, rel in _iter_py_files(scan_dir):
            try:
                with open(fpath, encoding="utf-8") as f:
                    raw = f.read()
            except OSError:
                continue
            stripped = _strip_comments(raw)
            if leak_str in stripped:
                violations.append(rel)

    assert violations == [], (
        f"Product-specific string '{leak_str}' found in engine executable code "
        f"(comments stripped). These strings belong in tests/fixtures/ or "
        f"assumption sets, not in engine defaults.\n"
        f"Files: {violations}"
    )


# ── Test 2: Gaidica never appears as a source= value ─────────────────────────

def test_gaidica_not_in_any_source_argument():
    """
    'Gaidica' must not appear as a literal value in any source= keyword argument
    anywhere under app/. This is the specific defect Rule 2 guards against:
    operator primary research being baked into engine defaults.
    """
    violations: list[str] = []
    for scan_dir in _SCAN_DIRS:
        for fpath, rel in _iter_py_files(scan_dir):
            try:
                with open(fpath, encoding="utf-8") as f:
                    raw = f.read()
            except OSError:
                continue
            # Only check non-comment lines for source= assignments
            stripped = _strip_comments(raw)
            if "Gaidica" in stripped:
                violations.append(rel)

    assert violations == [], (
        "Gaidica appears as an engine value (not just a comment) in:\n"
        + "\n".join(violations)
        + "\nPer addendum Rule 2, operator primary research belongs in "
        "assumption-set overrides, not engine code."
    )


# ── Test 3: assumed fractions flagged with ⚠ or method='assumed' ─────────────

def test_life_sciences_research_funnel_fractions_carry_warning():
    """
    The funnel-gate constants in market_segmentation.py that are assumed
    (not sourced from a published dataset) must carry an ⚠ marker in their
    adjacent comment, ensuring they surface as assumed in assumption ledgers.
    """
    path = os.path.join(_REPO_ROOT, "app", "services", "market_segmentation.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()

    # Each assumed fraction constant must have ⚠ somewhere near its definition
    assumed_constants = ["FRAC_LONG_DURATION", "FRAC_LOW_BANDWIDTH", "FRAC_NOT_CUSTOM"]
    for const in assumed_constants:
        # Find the line(s) containing the constant definition
        pattern = re.compile(rf"^{re.escape(const)}\s*[:=]", re.MULTILINE)
        match = pattern.search(src)
        assert match is not None, (
            f"Constant {const} not found in market_segmentation.py"
        )
        # Check that ⚠ appears nearby (within 3 lines)
        start = src.rfind("\n", 0, match.start()) + 1
        end = match.end() + 200
        window = src[start:end]
        assert "⚠" in window or "assumed" in window.lower(), (
            f"{const} in market_segmentation.py must carry '⚠' or 'assumed' "
            "marker to surface in assumption ledgers. "
            f"Context: {window[:120]!r}"
        )


# ── Test 4: source strings in segment nodes must not name a specific person ───

def test_segment_node_sources_are_generic():
    """
    SegmentNode source= strings must not contain a personal name or internal
    dataset label. They should be generic ('Assumed', 'Carnegie 2021', etc.)
    or reference a public dataset.

    This catches the pattern where a specific researcher's private cohort data
    is hardcoded as the source attribution for a node that applies to all products.
    """
    path = os.path.join(_REPO_ROOT, "app", "services", "market_segmentation.py")
    with open(path, encoding="utf-8") as f:
        src = f.read()

    # Find all source= string literals
    source_pattern = re.compile(r'source\s*=\s*["\']([^"\']+)["\']')
    found: list[str] = source_pattern.findall(src)

    # A source string looks like a person's name if it starts with a capitalized
    # word that is not one of the known acceptable institutional sources.
    KNOWN_INSTITUTIONS = {
        "Carnegie", "NSF", "NIH", "HERD", "Assumed", "CMS", "FDA",
        "WHO", "IQVIA", "CDC", "Census", "BLS", "AHRQ",
    }
    violations: list[str] = []
    for s in found:
        first_word = s.split()[0].rstrip(",.:;")
        if (
            first_word[0].isupper()
            and first_word not in KNOWN_INSTITUTIONS
            and not first_word.startswith("http")
            and "Assumed" not in s
            and "operator" in s.lower() or "assumed" in s.lower() or
            first_word in KNOWN_INSTITUTIONS or s.startswith("http")
        ):
            pass  # OK
        # Simpler check: reject strings that look like "Surname primary research..."
        # pattern: starts with a word not in known institutions
        if (
            first_word not in KNOWN_INSTITUTIONS
            and not s.startswith("http")
            and "Assumed" not in s
            and "assumed" not in s.lower()
            and "operator" not in s.lower()
            and first_word[0].isupper()
            and len(first_word) > 3
        ):
            violations.append(s)

    assert violations == [], (
        "Segment node source= strings appear to reference a specific person or "
        "private dataset rather than a public source or 'Assumed' marker:\n"
        + "\n".join(violations)
    )
