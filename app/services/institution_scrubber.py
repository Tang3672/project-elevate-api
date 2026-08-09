"""
C-03 — Institution name scrubber.

Institution is an entity type. It must come from intake (the user's submitted
idea text or the explicit `institution` parameter) or render generically.
The LLM must never fabricate a specific institution name in action items.

This module provides a post-processing scrubber that replaces any TTO/OTL
reference whose institution name is not grounded in the intake text with the
generic phrase "your institution's TTO".
"""

from __future__ import annotations

import re

# Matches: [1-4 title-cased words or all-caps abbreviation] + TTO/OTL/OTLC suffix
# Examples caught: "MIT TTO", "Stanford OTL", "Johns Hopkins TTO", "UCSF OTLC"
# Also catches long-form: "Stanford Office of Technology Licensing",
# "Harvard Technology Transfer Office"
_C03_RE = re.compile(
    r"\b"
    r"((?:[A-Z][A-Za-z]+\s+){0,3}[A-Z][A-Za-z]+)"  # group 1: institution name
    r"\s+"
    r"(?:TTO|OTL|OTLC"
    r"|Office\s+of\s+Technology(?:\s+Licensing)?"
    r"|Technology\s+Transfer(?:\s+Office)?)",
    re.UNICODE,
)

_GENERIC = "your institution's TTO"

# Short stop-words that can appear in the match but don't identify an institution
_STOP = frozenset({"the", "our", "your", "a", "an", "and", "or", "of", "at", "in", "with"})


def _is_grounded(inst_name: str, intake_lower: str) -> bool:
    """Return True if any significant word of inst_name appears in intake_lower."""
    words = [w for w in inst_name.lower().split() if w not in _STOP and len(w) > 2]
    return any(w in intake_lower for w in words)


def scrub_institution_refs(text: str, intake_lower: str) -> tuple[str, int]:
    """
    Replace TTO/OTL references whose institution name is not in the intake text.

    Returns (cleaned_text, replacement_count).
    """
    count = 0

    def _replace(m: re.Match) -> str:
        nonlocal count
        if _is_grounded(m.group(1), intake_lower):
            return m.group(0)
        count += 1
        return _GENERIC

    cleaned = _C03_RE.sub(_replace, text)
    return cleaned, count


def scrub_institution_fields(
    fields: dict[str, str | list],
    intake_lower: str,
) -> tuple[dict[str, str | list], int]:
    """
    Scrub multiple text fields (str or list[str]) in place.

    Returns (cleaned_fields_dict, total_replacement_count).
    """
    total = 0
    cleaned: dict = {}

    def _clean_value(val):
        nonlocal total
        if isinstance(val, str):
            v, n = scrub_institution_refs(val, intake_lower)
            total += n
            return v
        if isinstance(val, list):
            result = []
            for item in val:
                if isinstance(item, str):
                    v, n = scrub_institution_refs(item, intake_lower)
                    total += n
                    result.append(v)
                else:
                    result.append(item)
            return result
        return val

    for key, val in fields.items():
        cleaned[key] = _clean_value(val)

    return cleaned, total
