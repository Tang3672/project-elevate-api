"""
openFDA Device Verifier  (B-08)
================================
Resolves 510(k) K-numbers, De Novo (DEN) numbers, and PMA numbers against
the openFDA device databases at generation time.

Design:
  - Every K-number / DEN / PMA rendered in a report MUST pass through
    verify_510k() before rendering. On a miss → the citation is suppressed,
    not hallucinated.
  - Results are cached in-process (no repeated API calls per report).
  - Network failure → returns VerificationMiss (not an exception); the caller
    decides whether to suppress or display an unverified placeholder.

openFDA endpoints used:
  510(k): https://api.fda.gov/device/510k.json?search=k_number:K190358&limit=1
  De Novo: https://api.fda.gov/device/classification.json?search=device_name:...&limit=5
  PMA:     https://api.fda.gov/device/pma.json?search=pma_number:P210040&limit=1

All endpoints are free, no API key needed for low-volume use.
Rate limit: 240 req/min unauthenticated.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_OPENFDA_510K_URL  = "https://api.fda.gov/device/510k.json"
_OPENFDA_PMA_URL   = "https://api.fda.gov/device/pma.json"
_TIMEOUT           = 8.0
_DELAY             = 0.25   # seconds between requests to respect rate limit

# In-process cache: {number -> VerificationResult}
_CACHE: dict[str, "VerificationResult"] = {}


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class VerificationHit:
    """Successfully resolved device submission."""
    number:        str              # K190358 / DEN190058 / P210040
    applicant:     str              # company name from FDA record
    device_name:   str              # generic/trade name from FDA record
    decision_date: str              # YYYY-MM-DD
    decision:      str              # e.g. "SESE" (Substantially Equivalent), "APPR"
    source_url:    str              # permalink to openFDA record
    verified:      bool = True

    def render_cite(self) -> str:
        """Canonical citation string for report use."""
        return (
            f"{self.number} — {self.applicant}, {self.device_name} "
            f"({self.decision_date[:4]})"
        )


@dataclass
class VerificationMiss:
    """Number not found or network error."""
    number:    str
    reason:    str              # "not_found" | "network_error" | "invalid_format"
    verified:  bool = False


VerificationResult = VerificationHit | VerificationMiss


# ── Format validators ─────────────────────────────────────────────────────────

_K_NUMBER_RE  = re.compile(r"^K\d{6}$",   re.I)
_PMA_NUMBER_RE = re.compile(r"^P\d{6,7}$", re.I)
_DEN_NUMBER_RE = re.compile(r"^DEN\d{6}$", re.I)


def _normalise_number(raw: str) -> str:
    return (raw or "").strip().upper().replace(" ", "")


def _is_510k(number: str) -> bool:
    return bool(_K_NUMBER_RE.match(number))


def _is_pma(number: str) -> bool:
    return bool(_PMA_NUMBER_RE.match(number))


def _is_den(number: str) -> bool:
    return bool(_DEN_NUMBER_RE.match(number))


# ── API callers ───────────────────────────────────────────────────────────────

def _call_510k(number: str) -> VerificationResult:
    try:
        r = requests.get(
            _OPENFDA_510K_URL,
            params={"search": f"k_number:{number}", "limit": 1},
            timeout=_TIMEOUT,
        )
        if r.status_code == 404:
            return VerificationMiss(number=number, reason="not_found")
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return VerificationMiss(number=number, reason="not_found")
        rec = results[0]
        applicant   = rec.get("applicant", "Unknown applicant")
        device_name = rec.get("device_name", rec.get("generic_name", "Unknown device"))
        decision_date = rec.get("decision_date", "")[:10]
        decision    = rec.get("decision", "")
        url = f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpmn/pmn.cfm?ID={number}"
        return VerificationHit(
            number=number,
            applicant=applicant,
            device_name=device_name,
            decision_date=decision_date,
            decision=decision,
            source_url=url,
        )
    except requests.RequestException as e:
        logger.warning("openFDA 510(k) lookup failed for %s: %s", number, e)
        return VerificationMiss(number=number, reason="network_error")


def _call_pma(number: str) -> VerificationResult:
    try:
        r = requests.get(
            _OPENFDA_PMA_URL,
            params={"search": f"pma_number:{number}", "limit": 1},
            timeout=_TIMEOUT,
        )
        if r.status_code == 404:
            return VerificationMiss(number=number, reason="not_found")
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results:
            return VerificationMiss(number=number, reason="not_found")
        rec = results[0]
        applicant   = rec.get("applicant", "Unknown applicant")
        device_name = rec.get("brand_name", rec.get("generic_name", "Unknown device"))
        decision_date = rec.get("decision_date", "")[:10]
        decision    = rec.get("decision_code", "APPR")
        url = f"https://www.accessdata.fda.gov/scripts/cdrh/cfdocs/cfpma/pma.cfm?id={number}"
        return VerificationHit(
            number=number,
            applicant=applicant,
            device_name=device_name,
            decision_date=decision_date,
            decision=decision,
            source_url=url,
        )
    except requests.RequestException as e:
        logger.warning("openFDA PMA lookup failed for %s: %s", number, e)
        return VerificationMiss(number=number, reason="network_error")


# ── Public API ────────────────────────────────────────────────────────────────

def verify_device_number(raw: str) -> VerificationResult:
    """
    Resolve a device submission number against openFDA.
    Caches results in-process to avoid duplicate API calls per report.

    Returns VerificationHit on success, VerificationMiss on failure.
    Callers must NOT render the unverified applicant name or device name —
    only render data from the VerificationHit.
    """
    number = _normalise_number(raw)
    if not number:
        return VerificationMiss(number=raw, reason="invalid_format")

    if number in _CACHE:
        return _CACHE[number]

    time.sleep(_DELAY)

    if _is_510k(number):
        result = _call_510k(number)
    elif _is_pma(number):
        result = _call_pma(number)
    elif _is_den(number):
        # De Novo numbers don't have a direct API; return miss with a note
        result = VerificationMiss(number=number, reason="not_found")
        logger.info("De Novo number %s: no direct openFDA API; suppressing citation", number)
    else:
        result = VerificationMiss(number=number, reason="invalid_format")
        logger.warning("Device number %r does not match K/P/DEN format; suppressing", raw)

    _CACHE[number] = result
    return result


def extract_device_numbers(text: str) -> list[str]:
    """
    Extract all K-numbers, PMA numbers, and De Novo numbers from a text string.
    Used to scan LLM output for device numbers that need verification.
    """
    numbers = []
    # K-numbers: K followed by 6 digits
    numbers += re.findall(r"\bK\d{6}\b", text, re.I)
    # PMA numbers: P followed by 6-7 digits
    numbers += re.findall(r"\bP\d{6,7}\b", text, re.I)
    # De Novo: DEN followed by 6 digits
    numbers += re.findall(r"\bDEN\d{6}\b", text, re.I)
    return [n.upper() for n in numbers]


def verify_all_in_text(text: str) -> dict[str, VerificationResult]:
    """
    Extract and verify all device numbers found in a block of text.
    Returns {number: VerificationResult}.
    """
    numbers = extract_device_numbers(text)
    results = {}
    for n in set(numbers):
        results[n] = verify_device_number(n)
    return results


def scrub_unverified_device_numbers(text: str) -> tuple[str, list[str]]:
    """
    Replace unverified device numbers in text with '[device number not verified]'.
    Returns (scrubbed_text, list_of_scrubbed_numbers).

    Use this as a post-processing pass on all generated text sections that
    may contain device numbers.
    """
    numbers = list(set(extract_device_numbers(text)))
    if not numbers:
        return text, []

    scrubbed = []
    for n in numbers:
        result = verify_device_number(n)
        if not result.verified:
            text = re.sub(
                r"\b" + re.escape(n) + r"\b",
                "[device number not verified]",
                text,
                flags=re.I,
            )
            scrubbed.append(n)
            logger.info("B-08: scrubbed unverified device number %s (%s)", n, result.reason)
        else:
            # Replace with canonical citation
            hit = result  # VerificationHit
            text = re.sub(
                r"\b" + re.escape(n) + r"\b",
                f"{n} ({hit.applicant}, {hit.device_name[:40]}, {hit.decision_date[:4]})",
                text,
                flags=re.I,
            )

    return text, scrubbed
