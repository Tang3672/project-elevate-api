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
        "==========================================================================\n"
    )
