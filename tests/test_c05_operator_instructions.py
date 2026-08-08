"""
C-05 — operator instructions must not appear in output fields.

Spec v5 C-05: strings addressed to the operator ("operator should",
"n should be expanded", "specify source") are internal artifacts.
They belong in code comments, not in source/rationale fields that
render to users as citations.

Rule: unsourced values carry method="assumed" and no source string —
or a generic "Modeled — no primary source" label. Never a TODO.

All tests are pure source-inspection of the Python service files;
no API key, no DB.
"""

from __future__ import annotations

import ast
import os
import re

_SRC_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "app")
)

# Strings that must never appear in user-facing source/rationale fields
_FORBIDDEN = [
    "operator should",
    "n should be expanded",
    "specify source",
    "operator must",
    "you should supply",
    "you must supply",
    "todo: supply",
    "todo: add",
]

# Files whose SOURCE / RATIONALE string literals are checked
_TARGET_FILES = [
    "services/market_segmentation.py",
    "services/market_sizing_derivation_service.py",
    "services/buyer_model.py",
    "market/priors/life_sciences_research.py",
]


def _read(rel: str) -> str:
    with open(os.path.join(_SRC_ROOT, rel), encoding="utf-8") as f:
        return f.read()


class TestOperatorInstructionStrings:
    """String-literal scan of service files for forbidden instruction phrases."""

    def _string_literals(self, src: str) -> list[str]:
        """Extract non-docstring string literals from a Python source string.

        Docstrings (the first string expression in a module/class/function body)
        are developer documentation, not user-facing output, so they are excluded.
        """
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return []
        # Collect the AST id of every docstring node so we can skip them
        docstring_ids: set[int] = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef,
                                  ast.FunctionDef, ast.AsyncFunctionDef)):
                if (node.body
                        and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)):
                    docstring_ids.add(id(node.body[0].value))
        literals = []
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and id(node) not in docstring_ids):
                literals.append(node.value)
        return literals

    def test_market_segmentation_source_fields_clean(self):
        src = _read("services/market_segmentation.py")
        literals = self._string_literals(src)
        for lit in literals:
            low = lit.lower()
            for phrase in _FORBIDDEN:
                assert phrase not in low, (
                    f"Forbidden phrase {phrase!r} found in a string literal in "
                    f"market_segmentation.py: {lit!r}"
                )

    def test_market_sizing_derivation_source_fields_clean(self):
        src = _read("services/market_sizing_derivation_service.py")
        literals = self._string_literals(src)
        for lit in literals:
            low = lit.lower()
            for phrase in _FORBIDDEN:
                assert phrase not in low, (
                    f"Forbidden phrase {phrase!r} found in market_sizing_derivation_service.py: "
                    f"{lit!r}"
                )

    def test_buyer_model_spend_source_clean(self):
        src = _read("services/buyer_model.py")
        literals = self._string_literals(src)
        for lit in literals:
            low = lit.lower()
            for phrase in _FORBIDDEN:
                assert phrase not in low, (
                    f"Forbidden phrase {phrase!r} found in buyer_model.py: {lit!r}"
                )

    def test_life_sciences_research_priors_clean(self):
        src = _read("market/priors/life_sciences_research.py")
        literals = self._string_literals(src)
        for lit in literals:
            low = lit.lower()
            for phrase in _FORBIDDEN:
                assert phrase not in low, (
                    f"Forbidden phrase {phrase!r} found in life_sciences_research.py: {lit!r}"
                )


class TestAssumedSourceLabel:
    """When a value is modeled/assumed, its source label must be generic, not instructional."""

    def test_assumed_source_label_format_in_segmentation(self):
        src = _read("services/market_segmentation.py")
        # All source= strings that accompany assumed nodes must follow the approved pattern
        for m in re.finditer(r'source\s*=\s*["\']([^"\']+)["\']', src):
            label = m.group(1).lower()
            if "assumed" in label or "modeled" in label:
                assert "operator" not in label, (
                    f"Assumed source string must not instruct the operator: {m.group(1)!r}"
                )
                assert "should" not in label, (
                    f"Assumed source string must not contain 'should': {m.group(1)!r}"
                )

    def test_assumed_source_label_format_in_derivation_service(self):
        src = _read("services/market_sizing_derivation_service.py")
        for m in re.finditer(r'(?:sp_src|pop_src|source)\s*=\s*["\']([^"\']+)["\']', src):
            label = m.group(1).lower()
            if "assumed" in label or "modeled" in label:
                assert "operator" not in label, (
                    f"Source string must not instruct the operator: {m.group(1)!r}"
                )
                assert "should" not in label, (
                    f"Source string must not contain 'should': {m.group(1)!r}"
                )

    def test_no_todo_in_source_strings_across_app(self):
        """Scan all Python files in app/ for TODO inside string literals."""
        found = []
        for root, _, files in os.walk(_SRC_ROOT):
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    literals = []
                    try:
                        for node in ast.walk(ast.parse(content)):
                            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                                literals.append(node.value)
                    except SyntaxError:
                        continue
                    for lit in literals:
                        if re.search(r'\btodo\b.*(?:supply|source|specify)', lit, re.I):
                            rel = os.path.relpath(fpath, _SRC_ROOT)
                            found.append(f"{rel}: {lit!r}")
                except OSError:
                    continue
        assert not found, (
            "TODO-instruction strings found in source literals:\n" + "\n".join(found)
        )
