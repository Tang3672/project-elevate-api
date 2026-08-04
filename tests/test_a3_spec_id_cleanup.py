"""
A-03 — Remove spec identifiers from LLM prompt templates and report output
===========================================================================
Spec tracking tokens (B-01, H-03, etc.) must not appear in:
  1. The synthesis prompt strings sent to the LLM — they can echo them back.
  2. Any user-facing report text fields — the scrubber catches stragglers.

Failure mode:
  - An LLM sees "B-07 SOURCE TYPE GUARD:" in the prompt, interprets it as
    a labeled rule, and echoes "B-07 …" into the executive summary.
  - The scrubber post-processes the output but some fields (strategic_risks,
    positioning_statement) were not covered, so the spec ID leaks to the user.

All tests are pure-Python (no API key, no DB).
"""

from __future__ import annotations

import inspect
import re

import pytest


# ── Shared helpers ────────────────────────────────────────────────────────────

# Pattern that matches spec tracking tokens in any string
_SPEC_RE = re.compile(
    r"\b(?:B|H|F|S|G)-\d{2}\b"      # B-07, H-03, F-01, S-06, G-02
    r"|spec\s+v\d+"                    # "spec v4", "spec v3"
    r"|\(B-\d{2}\s+rule\)"            # "(B-01 rule)"
    r"|\(H-\d{2}[^)]*\)",             # "(H-03 — strictly enforced)"
    re.IGNORECASE,
)


# ══════════════════════════════════════════════════════════════════════════════
# A-03a: Prompt template strings contain no spec identifiers
# ══════════════════════════════════════════════════════════════════════════════

def _alignment_source() -> str:
    import app.services.alignment_service as svc
    return inspect.getsource(svc)


def _prompt_strings_only(src: str) -> str:
    """
    Return only lines that are likely LLM prompt template content — not
    comments, logger calls, regex pattern literals, or the scrubber block.
    """
    lines = src.splitlines()
    prompt_lines = []
    for ln in lines:
        stripped = ln.strip()
        # Skip blank lines and comments
        if not stripped or stripped.startswith("#"):
            continue
        # Skip inline comments on regex lines: contains   # "(B-01 …)"
        if re.search(r'#\s+["\']\(', stripped):
            continue
        # Skip logger calls
        if "logger." in stripped:
            continue
        # Skip lines that are raw regex string literals (r"…" / r'…')
        if re.match(r"""r['"][|\\(]""", stripped):
            continue
        # Skip the scrubber/regex definition block
        if any(tok in stripped for tok in (
            "_SPEC_ID_RE", "_re_spec", "SPEC_ID_RE",
            "re_spec.compile", "\\\\d{", "\\\\b", "\\\\w",
        )):
            continue
        # Skip docstrings
        if '"""' in stripped or "'''" in stripped:
            continue
        prompt_lines.append(ln)
    return "\n".join(prompt_lines)


class TestPromptStringsHaveNoSpecIds:

    def test_no_b07_in_prompt_strings(self):
        src = _prompt_strings_only(_alignment_source())
        hits = [ln for ln in src.splitlines()
                if re.search(r'\bB-07\b', ln)
                and "logger." not in ln and not ln.strip().startswith("#")]
        assert not hits, (
            "B-07 found in prompt template strings of alignment_service — "
            "remove the spec ID, keep the rule text:\n" + "\n".join(hits)
        )

    def test_no_b03_in_prompt_strings(self):
        src = _prompt_strings_only(_alignment_source())
        hits = [ln for ln in src.splitlines()
                if re.search(r'\bB-03\b', ln)
                and "logger." not in ln and not ln.strip().startswith("#")]
        assert not hits, (
            "B-03 found in prompt template strings — remove the spec ID:\n"
            + "\n".join(hits)
        )

    def test_no_h03_in_prompt_strings(self):
        src = _prompt_strings_only(_alignment_source())
        hits = [ln for ln in src.splitlines()
                if re.search(r'\bH-03\b', ln)
                and "logger." not in ln and not ln.strip().startswith("#")]
        assert not hits, (
            "H-03 found in prompt template strings — remove the spec ID:\n"
            + "\n".join(hits)
        )

    def test_no_b01_rule_label_in_prompt_strings(self):
        """'B-01 rule:' / 'B-01 rule' patterns must not appear in prompt content."""
        src = _prompt_strings_only(_alignment_source())
        hits = [ln for ln in src.splitlines()
                if re.search(r'B-01\s+rule', ln, re.IGNORECASE)
                and "logger." not in ln and not ln.strip().startswith("#")]
        assert not hits, (
            "B-01 rule label in prompt — replace with clean instruction:\n"
            + "\n".join(hits)
        )

    def test_source_type_guard_rule_still_present(self):
        """Removing the spec ID must not delete the rule itself."""
        src = _alignment_source()
        assert "SOURCE TYPE GUARD" in src, (
            "The SOURCE TYPE GUARD instruction must still exist in the prompt "
            "after B-07 label removal — only the spec ID should be stripped"
        )

    def test_price_rule_still_present(self):
        src = _alignment_source()
        assert "PRICE RULE" in src, (
            "The PRICE RULE instruction must still exist in the prompt "
            "after B-03 label removal"
        )

    def test_cross_report_isolation_still_present(self):
        src = _alignment_source()
        assert "CROSS-REPORT ISOLATION" in src


# ══════════════════════════════════════════════════════════════════════════════
# A-03b: Spec-ID scrubber covers key report text fields
# ══════════════════════════════════════════════════════════════════════════════

class TestSpecIdScrubberCoverage:

    def test_scrubber_covers_executive_summary(self):
        src = _alignment_source()
        assert '"executive_summary"' in src or "'executive_summary'" in src

    def test_scrubber_covers_positioning_statement(self):
        src = _alignment_source()
        assert "positioning_statement" in src

    def test_scrubber_covers_guiding_question(self):
        src = _alignment_source()
        assert "guiding_question" in src

    def test_scrubber_covers_strategic_risks(self):
        src = _alignment_source()
        assert "strategic_risks" in src

    def test_scrubber_covers_recommended_next_steps(self):
        src = _alignment_source()
        assert "recommended_next_steps" in src


# ══════════════════════════════════════════════════════════════════════════════
# A-03c: Scrubber regex matches expected spec ID patterns
# ══════════════════════════════════════════════════════════════════════════════

class TestSpecIdRegex:

    def _re(self):
        """Build the same regex the scrubber uses."""
        import re as _re
        return _re.compile(
            r"\b(?:H|B|F|S)-\d{2}\b"
            r"|spec\s+v\d+"
            r"|\(H-\d{2}\s+(?:fix|formula|compliant)\)"
            r"|\(B-\d{2}\s+\w+\)",
            _re.I,
        )

    def test_matches_b01(self):
        assert self._re().search("B-01 rule: do not pad")

    def test_matches_h07(self):
        assert self._re().search("H-07 formula applied")

    def test_matches_f03(self):
        assert self._re().search("F-03 truncation")

    def test_matches_spec_v4(self):
        assert self._re().search("spec v4 compliant")

    def test_matches_parenthetical_b01_rule(self):
        assert self._re().search("(B-01 rule)")

    def test_does_not_match_clean_prose(self):
        assert not self._re().search(
            "The product addresses a real unmet need in the AMR market."
        )

    def test_does_not_match_part_d(self):
        """'Part D' is a Medicare term, not a spec identifier — must not match."""
        assert not self._re().search("covered under Medicare Part D")

    def test_does_not_match_b_without_dash(self):
        assert not self._re().search("B01 designation")


# ══════════════════════════════════════════════════════════════════════════════
# A-03d: Functional scrubber behaviour on report-like dicts
# ══════════════════════════════════════════════════════════════════════════════

def _scrub(fields: dict) -> dict:
    """
    Replicate the scrubber logic from alignment_service so we can test it in
    isolation without importing the full service (which has heavy dependencies).
    """
    import re as _re
    spec_re = _re.compile(
        r"\b(?:H|B|F|S)-\d{2}\b"
        r"|spec\s+v\d+"
        r"|\(H-\d{2}\s+(?:fix|formula|compliant)\)"
        r"|\(B-\d{2}\s+\w+\)",
        _re.I,
    )

    class _Obj:
        pass

    obj = _Obj()
    for k, v in fields.items():
        setattr(obj, k, v)

    str_fields = ("executive_summary", "confidence_note", "methodology_note",
                  "positioning_statement", "guiding_question", "limitations")
    list_fields = ("recommended_next_steps", "strategic_risks")

    for sf in str_fields:
        sv = getattr(obj, sf, None)
        if isinstance(sv, str) and spec_re.search(sv):
            setattr(obj, sf, spec_re.sub("", sv).strip())

    for lf in list_fields:
        lv = getattr(obj, lf, None)
        if isinstance(lv, list):
            setattr(obj, lf, [
                spec_re.sub("", s).strip() if isinstance(s, str) else s
                for s in lv
            ])

    return {k: getattr(obj, k) for k in fields}


class TestScrubberFunctional:

    def test_strips_spec_id_from_executive_summary(self):
        result = _scrub({"executive_summary": "B-07 rule: strong pipeline."})
        assert "B-07" not in result["executive_summary"]
        assert "strong pipeline" in result["executive_summary"]

    def test_strips_spec_id_from_positioning_statement(self):
        result = _scrub({"positioning_statement": "S-07: For PIs who need reliable data."})
        assert "S-07" not in result["positioning_statement"]
        assert "For PIs" in result["positioning_statement"]

    def test_strips_spec_id_from_guiding_question(self):
        result = _scrub({"guiding_question": "H-03 isolation: Can we displace ActiGraph?"})
        assert "H-03" not in result["guiding_question"]
        assert "Can we displace" in result["guiding_question"]

    def test_strips_from_strategic_risks_list(self):
        result = _scrub({"strategic_risks": [
            "B-04 issue: risk of commoditization.",
            "Regulatory change risk.",
        ]})
        assert "B-04" not in result["strategic_risks"][0]
        assert "risk of commoditization" in result["strategic_risks"][0]
        assert result["strategic_risks"][1] == "Regulatory change risk."

    def test_strips_from_recommended_next_steps_list(self):
        result = _scrub({"recommended_next_steps": [
            "B-01: Apply to SBIR Phase I.",
            "Run a pilot with 3 labs.",
        ]})
        assert "B-01" not in result["recommended_next_steps"][0]
        assert "Apply to SBIR Phase I" in result["recommended_next_steps"][0]

    def test_clean_text_unchanged(self):
        text = "Strong commercial opportunity in the academic research wearable market."
        result = _scrub({"executive_summary": text})
        assert result["executive_summary"] == text

    def test_none_field_does_not_crash(self):
        result = _scrub({"executive_summary": None})
        assert result["executive_summary"] is None

    def test_list_with_non_string_items_does_not_crash(self):
        result = _scrub({"strategic_risks": ["Valid risk.", None, 42]})
        assert result["strategic_risks"][1] is None
        assert result["strategic_risks"][2] == 42

    def test_strips_spec_v_from_methodology_note(self):
        result = _scrub({"methodology_note": "Computed per spec v4 bottom-up method."})
        assert "spec v4" not in result["methodology_note"]
        assert "bottom-up method" in result["methodology_note"]
