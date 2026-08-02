"""
Segment Resolver  (Part C of Build Spec v2)
===========================================
Maps a product description + disease to the best-fit treatable segment.

resolve_segment(idea_text, disease_name, product_type)
  → {segment, confidence, alternatives, needs_clarification}

Auto-narrows from disease to the specific clinical pathway the product fits.
If no segment matches confidently (score < 0.30 or top two segments are
within 0.15 of each other), returns needs_clarification=True so the
clarifying-questions flow can ask the PI which segment applies.

Prevents the "all stroke patients" failure: a product matching the LVO
thrombectomy segment will get the thrombectomy funnel, not whole-disease TAM.
"""

import re
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)

_MIN_CONFIDENCE = 0.30   # below this → needs_clarification
_MIN_GAP = 0.15          # top-2 gap below this → needs_clarification (ambiguous)


async def resolve_segment(
    idea_text: str,
    disease_name: str,
    product_type: str = "",
) -> dict:
    """
    Resolve which market segment best matches this product and disease.

    Returns:
        {
          "segment":             dict | None,   # best-fit segment row
          "confidence":          float,          # 0-1 match score
          "alternatives":        list[dict],     # ranked other candidates
          "needs_clarification": bool,           # True → ask PI to pick segment
          "match_reason":        str,            # human-readable explanation
        }
    """
    from app.db.market_segment_repository import get_segments_for_disease

    segments = await get_segments_for_disease(disease_name)
    if not segments:
        return {
            "segment": None,
            "confidence": 0.0,
            "alternatives": [],
            "needs_clarification": False,  # no data → use existing DisMod engine
            "match_reason": f"No seeded segments for '{disease_name}' — using TA-level defaults.",
        }

    idea_lower = _normalize(idea_text + " " + product_type)
    scored = []
    for seg in segments:
        score, matched_kws = _score_segment(seg, idea_lower)
        scored.append((score, matched_kws, seg))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_score, top_kws, top_seg = scored[0]
    alternatives = [s for _, _, s in scored[1:]]

    # Determine if auto-selection is confident
    second_score = scored[1][0] if len(scored) > 1 else 0.0
    gap = top_score - second_score

    if top_score < _MIN_CONFIDENCE:
        return {
            "segment": None,
            "confidence": top_score,
            "alternatives": [s for _, _, s in scored],
            "needs_clarification": True,
            "match_reason": (
                f"No segment matched with sufficient confidence (best: {top_score:.0%} "
                f"for '{top_seg.get('segment_name')}'). "
                f"Available segments: {[s.get('segment_name') for s in segments]}. "
                "PI should select the applicable segment."
            ),
        }

    if len(scored) > 1 and gap < _MIN_GAP:
        return {
            "segment": top_seg,
            "confidence": top_score,
            "alternatives": alternatives,
            "needs_clarification": True,
            "match_reason": (
                f"Ambiguous match: '{top_seg.get('segment_name')}' ({top_score:.0%}) vs "
                f"'{scored[1][2].get('segment_name')}' ({second_score:.0%}) — gap {gap:.0%} "
                f"< {_MIN_GAP:.0%} threshold. PI should confirm segment."
            ),
        }

    kw_list = ", ".join(f"'{k}'" for k in top_kws[:4])
    return {
        "segment": top_seg,
        "confidence": top_score,
        "alternatives": alternatives,
        "needs_clarification": False,
        "match_reason": (
            f"Matched '{top_seg.get('segment_name')}' with {top_score:.0%} confidence "
            f"via keywords: {kw_list}."
        ),
    }


def _score_segment(seg: dict, idea_lower: str) -> tuple:
    """
    Score a segment against the normalized idea text.
    Returns (score 0-1, list of matched keywords).
    """
    keywords = seg.get("product_fit_keywords") or []
    if isinstance(keywords, str):
        import json
        try:
            keywords = json.loads(keywords)
        except Exception:
            keywords = [keywords]

    if not keywords:
        return 0.0, []

    matched = []
    for kw in keywords:
        kw_norm = _normalize(kw)
        # Full phrase match scores higher than word-by-word
        if kw_norm in idea_lower:
            matched.append(kw)
        elif all(word in idea_lower for word in kw_norm.split() if len(word) > 2):
            matched.append(kw)

    score = len(matched) / len(keywords)

    # Boost score if the pathway_tag itself appears in the idea
    pathway = _normalize(seg.get("pathway_tag") or "")
    if pathway and any(part in idea_lower for part in pathway.split("_") if len(part) > 3):
        score = min(1.0, score + 0.10)

    return score, matched


def _normalize(text: str) -> str:
    """Lowercase + collapse whitespace, remove punctuation for matching."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def format_resolution_for_log(result: dict) -> str:
    seg = result.get("segment")
    if seg:
        return (
            f"Resolved to '{seg.get('segment_name')}' "
            f"(confidence={result['confidence']:.0%}, "
            f"needs_clarification={result['needs_clarification']})"
        )
    return f"No segment resolved (needs_clarification={result['needs_clarification']})"
