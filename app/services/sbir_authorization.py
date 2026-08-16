"""SBIR/STTR Program Authorization Status Lookup Table.

UPDATE THIS WHENEVER AUTHORIZATION STATUS CHANGES.
Primary source: https://grants.nih.gov/grants/funding/sbir.htm
Also: NIH Guide Notices (grants.nih.gov/grants/guide)

Background: SBIR/STTR requires periodic Congressional reauthorization.
The program has lapsed briefly (e.g., 2022, late 2025) during CR gaps,
then been reauthorized. Reports must reflect the current status to avoid
contradicting the deterministic sbir_fit score with stale LLM prose.
"""

from __future__ import annotations

# ── Authorization record ───────────────────────────────────────────────────────
# authorized:   True = program accepting applications now
# verified_at:  ISO date of last manual verification (update when you check)
# expires:      Known expiry date (empty if reauthorized indefinitely)
# notice:       Most recent NIH Notice describing current status

SBIR_AUTH: dict = {
    "authorized": True,
    "verified_at": "2026-08-15",
    "expires": "",
    "notice": "NOT-OD-26-006",
    "notes": (
        "NIH Notice NOT-OD-26-006 announced SBIR/STTR would lapse effective "
        "October 1, 2025 without Congressional reauthorization. The program has "
        "historically been reauthorized via continuing resolutions or appropriations. "
        "Current status reflects best-available information as of the verified_at date. "
        "Always confirm at grants.nih.gov/grants/funding/sbir.htm before advising "
        "on SBIR applications."
    ),
}


def is_sbir_authorized() -> bool:
    """Return True if SBIR/STTR is currently accepting applications."""
    return bool(SBIR_AUTH.get("authorized"))


def get_sbir_context_block() -> str:
    """Return an authoritative SBIR status block for LLM context injection.

    Injected into the expert prompt so the model uses the lookup table's status
    rather than stale training-data claims about authorization lapses.
    """
    status = "AUTHORIZED — accepting new applications" if SBIR_AUTH["authorized"] else "LAPSED — not currently accepting new applications"
    caution = (
        "Do NOT state or imply that SBIR has expired or is unauthorized."
        if SBIR_AUTH["authorized"]
        else "Do NOT show high sbir_fit scores. The program is not currently accepting new applications."
    )
    return (
        "\n=== SBIR/STTR AUTHORIZATION STATUS (authoritative — overrides training data) ===\n"
        f"Status: {status}\n"
        f"Verified: {SBIR_AUTH['verified_at']}\n"
        f"Notes: {SBIR_AUTH['notes']}\n"
        f"RULE: {caution} Reference only the status above; do not cite "
        f"NIH Notice {SBIR_AUTH['notice']} as evidence of current lapse.\n"
        "\n"
        "NIH SEED CLARIFICATION:\n"
        "  NIH SEED (Small Business Education and Entrepreneurial Development) is the\n"
        "  NIH office that administers SBIR/STTR programs — it covers ONLY small-business\n"
        "  mechanisms (R43/R44/R41/R42).  Do NOT cite NIH SEED as the source for R01,\n"
        "  R21, R03, U01, or any other investigator-initiated grant success rates.\n"
        "  For R01 success rates, cite: NIH OER — https://grants.nih.gov/grants/grant_types/r01.htm\n"
        "  For IC-specific paylines, cite: https://nexus.od.nih.gov (NIH Nexus blog).\n"
        "\n"
        "SOURCE URL RULES (apply to every source_url field you generate):\n"
        "  1. A source_url MUST point to a specific data record, page, or document — not\n"
        "     a generic search results page.\n"
        "  2. NEVER use reporter.nih.gov/search as a source_url — this is a search form,\n"
        "     not data.  Use https://reporter.nih.gov/project-details/<appl_id> for\n"
        "     specific grants, or omit the URL entirely.\n"
        "  3. NEVER use pubmed.ncbi.nlm.nih.gov without a PMID in the URL path.\n"
        "     Correct:   https://pubmed.ncbi.nlm.nih.gov/38123456/\n"
        "     Incorrect: https://pubmed.ncbi.nlm.nih.gov/search/?term=...\n"
        "  4. Market-research aggregator sites (Grand View Research, MarketsandMarkets,\n"
        "     Mordor Intelligence, IMARC, Allied Market Research) are NOT acceptable\n"
        "     sources.  Use primary government or peer-reviewed sources only.\n"
        "==========================================================================\n"
    )
