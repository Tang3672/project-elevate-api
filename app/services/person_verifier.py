"""
Person Verifier  (H-06)
=======================
Enforces that no named person appears in the output unless they resolve
to a verifiable external source captured at retrieval time.

Root cause of defect:
  "Ayan Mukhopadhyay, WashU Neurotech Hub" appeared in the KOL list with
  no source URL and no retrieval provenance — fabricated from training data.

Design:
  1. `sanitize_kol_list()` — given LLM-generated KOL strings and the set of
     author names from a verified external source (Semantic Scholar), returns
     only the KOLs whose name appears in the verified set.
  2. `kol_selection_criteria_block()` — honest fallback when no verified KOLs
     pass (renders what criteria to use, not who meets them).
  3. `build_verified_kol_strings()` — formats verified Semantic Scholar KOLs
     with a stable S2 search URL so the source is captured at render time.

Caller: alignment_service.py, after the kol_block is built from Semantic Scholar
  and before injecting KOL names into the report. The LLM-generated
  key_opinion_leaders list is sanitized in post-processing.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

_S2_AUTHOR_URL_BASE = "https://api.semanticscholar.org/graph/v1/paper/search?query="
_PUBMED_AUTHOR_URL_BASE = "https://pubmed.ncbi.nlm.nih.gov/?term="


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class VerifiedKOL:
    """A key opinion leader whose identity was confirmed by an external source."""
    name:          str
    source_url:    str
    source_name:   str = "Semantic Scholar"
    paper_count:   int = 0
    citation_total: int = 0
    institution:   Optional[str] = None

    def format_line(self) -> str:
        parts = [self.name]
        if self.institution:
            parts.append(self.institution)
        parts.append(f"{self.paper_count} papers, {self.citation_total:,} citations")
        parts.append(f"[Source: {self.source_url}]")
        return " — ".join(parts)


@dataclass
class KOLSanitizationResult:
    verified:       list[VerifiedKOL] = field(default_factory=list)
    dropped_names:  list[str] = field(default_factory=list)
    criteria_block: str = ""
    used_fallback:  bool = False

    @property
    def has_verified(self) -> bool:
        return bool(self.verified)

    def formatted_list(self) -> list[str]:
        return [k.format_line() for k in self.verified]


# ── Name normalisation ────────────────────────────────────────────────────────

def _normalise(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace. For fuzzy name matching."""
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s.strip().lower())


def _name_in_string(author_name: str, kol_string: str) -> bool:
    """
    Return True if the author_name (from Semantic Scholar) appears in kol_string
    (from LLM output). Handles reformatting like "Dr. Smith" containing "Smith".
    Requires a 3-char minimum match to avoid false positives on single surnames.
    """
    norm_author = _normalise(author_name)
    norm_kol    = _normalise(kol_string)
    if len(norm_author) < 3:
        return False
    # Full-name match first
    if norm_author in norm_kol:
        return True
    # Last-name-only match (for "J. Doe" → "John Doe")
    last_name = norm_author.split()[-1]
    if len(last_name) >= 4 and last_name in norm_kol.split():
        return True
    return False


# ── Core functions ────────────────────────────────────────────────────────────

def build_verified_kol_list(kols: list[dict], disease_name: str = "") -> list[VerifiedKOL]:
    """
    Convert raw Semantic Scholar KOL dicts to VerifiedKOL objects.
    Each entry has a stable PubMed author search URL as its source.

    kols format (from get_kol_network):
      [{"name": str, "citation_total": int, "paper_count": int}, ...]
    """
    verified: list[VerifiedKOL] = []
    for k in kols:
        name = k.get("name") or k.get("author") or ""
        if not name:
            continue
        query = f"{name} {disease_name}".strip()
        source_url = _PUBMED_AUTHOR_URL_BASE + quote_plus(f"{name}[Author]")
        verified.append(VerifiedKOL(
            name=name,
            source_url=source_url,
            source_name="PubMed (author publications)",
            paper_count=k.get("paper_count", 0),
            citation_total=k.get("citation_total", 0),
        ))
    return verified


def sanitize_kol_list(
    llm_kol_strings: list[str],
    verified_kols: list[VerifiedKOL],
    disease_name: str = "",
    sub_expert_id: str = "",
) -> KOLSanitizationResult:
    """
    Filter LLM-generated KOL name strings against the verified KOL set.

    For each string in llm_kol_strings, check if any verified KOL's name
    appears in it. Strings with no match are dropped; matched verified KOLs
    are returned. If fewer than 2 verified KOLs pass, the criteria fallback
    is used instead.

    Returns a KOLSanitizationResult with verified list and/or criteria block.
    """
    if not verified_kols:
        result = KOLSanitizationResult(
            dropped_names=list(llm_kol_strings),
            criteria_block=kol_selection_criteria_block(sub_expert_id, disease_name),
            used_fallback=True,
        )
        if llm_kol_strings:
            logger.info(
                "H-06: no Semantic Scholar KOLs available for '%s'; "
                "dropped %d LLM-generated names, using criteria block",
                disease_name, len(llm_kol_strings),
            )
        return result

    matched: list[VerifiedKOL] = []
    matched_set: set[str] = set()
    dropped: list[str] = []

    for kol_str in llm_kol_strings:
        found = None
        for vk in verified_kols:
            if vk.name not in matched_set and _name_in_string(vk.name, kol_str):
                found = vk
                break
        if found:
            matched.append(found)
            matched_set.add(found.name)
        else:
            dropped.append(kol_str)

    if dropped:
        logger.info(
            "H-06: dropped %d unverified KOL name(s) for '%s': %s",
            len(dropped), disease_name, dropped[:3],
        )

    # Add any verified KOLs not yet in matched (from S2 data, not in LLM output)
    for vk in verified_kols:
        if vk.name not in matched_set:
            matched.append(vk)
            matched_set.add(vk.name)

    if len(matched) < 2:
        logger.info(
            "H-06: only %d verified KOL(s) for '%s'; using criteria block",
            len(matched), disease_name,
        )
        return KOLSanitizationResult(
            verified=matched,
            dropped_names=dropped,
            criteria_block=kol_selection_criteria_block(sub_expert_id, disease_name),
            used_fallback=True,
        )

    return KOLSanitizationResult(
        verified=matched,
        dropped_names=dropped,
        criteria_block="",
        used_fallback=False,
    )


# ── B-04: Person-name scan across all text fields ────────────────────────────
#
# Catches fabricated person references in fields OTHER than key_opinion_leaders
# (e.g. "Contact Dr. Reza Moheimani at UW" in recommended_next_steps).
# Strategy: match title-prefixed names (Dr./Prof./etc.) — very low false-positive
# rate. Bare "First Last" without a title prefix is too ambiguous and is skipped.

_TITLE_NAME_RE = re.compile(
    r"\b(Dr\.?|Prof\.?|Professor|Mr\.?|Ms\.?|Mrs\.?|Assoc\.?\s*Prof\.?|Asst\.?\s*Prof\.?)"
    r"\s+([A-Z][a-zA-Z'\-]{1,25}(?:\s+[A-Z][a-zA-Z'\-]{1,25}){1,3})",
    re.UNICODE,
)


def extract_titled_person_names(text: str) -> list[tuple[str, str]]:
    """
    Return list of (full_match, name_only) for title-prefixed person references
    in text. E.g. "Dr. Reza Moheimani" → ("Dr. Reza Moheimani", "Reza Moheimani").
    """
    found = []
    for m in _TITLE_NAME_RE.finditer(text):
        full   = m.group(0)
        name   = m.group(2).strip()
        found.append((full, name))
    return found


def scrub_unverified_titled_names(
    text: str,
    verified_name_set: set[str],
) -> tuple[str, list[str]]:
    """
    Replace title-prefixed person names that are NOT in verified_name_set with
    '[person reference removed — not in verified source list]'.

    Returns (scrubbed_text, list_of_removed_names).

    verified_name_set should contain normalised names from VerifiedKOL.name.
    """
    if not text:
        return text, []
    removed: list[str] = []
    for full_match, name in extract_titled_person_names(text):
        if _normalise(name) not in verified_name_set:
            text = text.replace(full_match, "[person reference removed — not in verified source list]", 1)
            removed.append(name)
    return text, removed


def scrub_text_fields_for_persons(
    fields: dict[str, str | list],
    verified_kols: list["VerifiedKOL"],
) -> tuple[dict[str, str | list], list[str]]:
    """
    B-04: Scan a dict of text fields for unverified titled person names and
    replace them in place.  Works on str values and list[str] values.

    fields: {"recommended_next_steps": [...], "executive_summary": "...", ...}
    verified_kols: the list returned by build_verified_kol_list()

    Returns (cleaned_fields, all_removed_names).
    """
    verified_name_set = {_normalise(vk.name) for vk in verified_kols}
    all_removed: list[str] = []
    cleaned: dict = {}

    for key, val in fields.items():
        if isinstance(val, str):
            new_val, removed = scrub_unverified_titled_names(val, verified_name_set)
            cleaned[key] = new_val
            all_removed.extend(removed)
        elif isinstance(val, list):
            new_list = []
            for item in val:
                if isinstance(item, str):
                    new_item, removed = scrub_unverified_titled_names(item, verified_name_set)
                    new_list.append(new_item)
                    all_removed.extend(removed)
                elif isinstance(item, dict):
                    new_dict = {}
                    for dk, dv in item.items():
                        if isinstance(dv, str):
                            new_dv, removed = scrub_unverified_titled_names(dv, verified_name_set)
                            new_dict[dk] = new_dv
                            all_removed.extend(removed)
                        else:
                            new_dict[dk] = dv
                    new_list.append(new_dict)
                else:
                    new_list.append(item)
            cleaned[key] = new_list
        else:
            cleaned[key] = val

    return cleaned, all_removed


def kol_selection_criteria_block(sub_expert_id: str = "", disease_name: str = "") -> str:
    """
    Honest fallback: render KOL selection criteria instead of a fabricated roster.
    Used when automated retrieval found no verified KOLs.

    The criteria describe what a KOL should look like, not who they are.
    Caller should insert this into the market_access.key_opinion_leaders field.
    """
    disease_part = f"in {disease_name}" if disease_name else "in this disease area"
    is_research_tool = "research_tool" in (sub_expert_id or "").lower()

    if is_research_tool:
        heading = "KOL SELECTION CRITERIA — RESEARCH TOOL CONTEXT"
        criteria = [
            f"≥5 publications {disease_part} using wearable or data-logging methods (last 5 years, PubMed)",
            "Active NIH/NSF grant with data-capture or longitudinal monitoring component (NIH Reporter)",
            "Conference presentations on remote neurophysiology data collection (SfN, IEEE EMBC, NeurIPS)",
            "Lab size ≥2 graduate students working on passive sensing or ambulatory monitoring",
            "Open-source tooling or datasets shared publicly (GitHub, PhysioNet, OpenNeuro)",
        ]
        start_tip = (
            f"Start with: PubMed search for ({disease_name or 'target area'}[MeSH] AND "
            "(wearable OR ambulatory monitoring OR data logging OR passive sensing)[Title/Abstract]) "
            "filtered to last 5 years."
        )
    else:
        heading = "KOL SELECTION CRITERIA"
        criteria = [
            f"≥10 publications {disease_part} in last 5 years (PubMed/Semantic Scholar)",
            "≥500 citations in domain (h-index ≥15 preferred)",
            "Principal investigator on active NIH grant in disease area (NIH Reporter)",
            "Lead investigator on Phase 2 or Phase 3 trial (ClinicalTrials.gov)",
            "Invited speaker or society leadership at major specialty conference (last 3 years)",
        ]
        start_tip = (
            f"Start with: PubMed author search for ({disease_name or 'disease area'}[MeSH Terms] "
            "AND Clinical Trial[pt]) filtered to last 5 years."
        )

    bullet_list = "\n".join(f"  • {c}" for c in criteria)
    return (
        f"[{heading}]\n"
        "No verified KOLs identified by automated retrieval. "
        "Manual identification recommended — target profiles meeting ≥3 of:\n"
        f"{bullet_list}\n"
        f"{start_tip}"
    )
