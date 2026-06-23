"""
Source URL Validator
=====================
Defends against dead / fabricated links: after a report is generated, every
source_url in it is checked in parallel; links that are *definitely* dead are
nulled (the citation name is kept, the broken link removed).

Calibrated to avoid false positives — we only drop a URL on an unambiguous
"this does not exist" signal:
  - HTTP 404 / 410
  - the domain does not resolve (DNS failure) / connection refused (after a retry)
Anything ambiguous (timeout, 5xx, 401/403/405 bot-blocking, other) is KEPT, so
valid-but-slow or anti-bot-protected links are never wrongly removed.

Runs in the async generation path, so the few seconds it costs are invisible.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_URL_KEYS = ("url", "source_url")
_MAX_URLS = 50
_CONCURRENCY = 12


def _collect_url_refs(obj, refs):
    """Recursively find every (container_dict, key) holding an http(s) URL."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _URL_KEYS and isinstance(v, str) and v.startswith("http"):
                refs.append((obj, k))
            else:
                _collect_url_refs(v, refs)
    elif isinstance(obj, list):
        for item in obj:
            _collect_url_refs(item, refs)


async def _check_one(client, url: str) -> tuple[str, bool]:
    """Return (url, is_dead). Dead only on 404/410 or DNS/conn failure (after retry)."""
    import httpx
    for attempt in range(2):
        try:
            r = await client.head(url, timeout=5.0)
            if r.status_code in (403, 405, 501):       # some servers reject HEAD
                r = await client.get(url, timeout=6.0)
            return url, r.status_code in (404, 410)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt == 0:
                await asyncio.sleep(0.5)               # one retry for transient blips
                continue
            return url, True                            # domain doesn't resolve / refused
        except Exception:
            return url, False                           # timeout/other -> keep (ambiguous)
    return url, False


async def clean_report_urls(report: dict) -> dict:
    """Validate all source URLs in the report dict; null the dead ones in place.
    Returns {checked, dead, dead_urls}. Best-effort — never raises into the pipeline."""
    try:
        import httpx
    except ImportError:
        return {"checked": 0, "dead": 0}

    refs: list = []
    _collect_url_refs(report, refs)
    urls = list({obj[key] for obj, key in refs})[:_MAX_URLS]
    if not urls:
        return {"checked": 0, "dead": 0}

    sem = asyncio.Semaphore(_CONCURRENCY)
    async with httpx.AsyncClient(headers={"User-Agent": _UA}, follow_redirects=True) as client:
        async def bound(u):
            async with sem:
                return await _check_one(client, u)
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*[bound(u) for u in urls]), timeout=20.0)
        except asyncio.TimeoutError:
            logger.warning("URL validation overall timeout — leaving links unchanged")
            return {"checked": len(urls), "dead": 0, "timed_out": True}

    dead = {u for u, is_dead in results if is_dead}
    if dead:
        for obj, key in refs:
            if obj.get(key) in dead:
                obj[key] = None
        logger.info("URL validation: %d/%d links dead, removed", len(dead), len(urls))
    return {"checked": len(urls), "dead": len(dead), "dead_urls": list(dead)[:10]}
