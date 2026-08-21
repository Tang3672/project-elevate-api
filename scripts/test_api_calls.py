"""
Pre-flight API call validator.
Run locally before deploying to catch Anthropic API errors without burning
a full report run ($$$). Tests the exact request shape used in production.

Usage:
    cd /Users/isaacwang/Downloads/ProjectElevate
    python scripts/test_api_calls.py
"""
import asyncio
import os
import sys
import httpx
from pathlib import Path

# Load .env
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
API_URL = "https://api.anthropic.com/v1/messages"
HEADERS_BASE = {
    "x-api-key": API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json",
}

PASS = "✅"
FAIL = "❌"
results = []


async def check(name: str, coro):
    try:
        await coro
        print(f"  {PASS} {name}")
        results.append((name, True, None))
    except Exception as e:
        msg = str(e)[:200]
        print(f"  {FAIL} {name}: {msg}")
        results.append((name, False, msg))


# ── helpers ───────────────────────────────────────────────────────────────────

async def post(payload: dict, extra_headers: dict = {}) -> dict:
    async with httpx.AsyncClient(timeout=30.0) as c:
        r = await c.post(API_URL, headers={**HEADERS_BASE, **extra_headers}, json=payload)
        if not r.is_success:
            raise ValueError(f"HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        # extract text block
        for block in body.get("content", []):
            if block.get("type") == "text":
                return block
        raise ValueError(f"No text block. content={body.get('content', [])[:2]}")


# ── Test 1: claude-sonnet-5 with thinking disabled (the synthesis call) ──────

async def test_sonnet5_thinking_disabled():
    await post({
        "model":      "claude-sonnet-5",
        "max_tokens": 100,
        "thinking":   {"type": "disabled"},
        "system":     "You are a helpful assistant.",
        "messages":   [{"role": "user", "content": "Reply with exactly: OK"}],
    })


# ── Test 2: claude-opus-5 with thinking disabled ─────────────────────────────

async def test_opus5_thinking_disabled():
    await post({
        "model":      "claude-opus-5",
        "max_tokens": 100,
        "thinking":   {"type": "disabled"},
        "system":     "You are a helpful assistant.",
        "messages":   [{"role": "user", "content": "Reply with exactly: OK"}],
    })


# ── Test 3: claude-haiku-4-5-20251001 (no thinking, no temperature) ──────────

async def test_haiku_basic():
    await post({
        "model":      "claude-haiku-4-5-20251001",
        "max_tokens": 50,
        "system":     "You are a helpful assistant.",
        "messages":   [{"role": "user", "content": "Reply with exactly: OK"}],
    })


# ── Test 4: haiku with temperature (still used in alignment.py) ──────────────

async def test_haiku_with_temperature():
    await post({
        "model":       "claude-haiku-4-5-20251001",
        "max_tokens":  50,
        "temperature": 0,
        "system":      "You are a helpful assistant.",
        "messages":    [{"role": "user", "content": "Reply with exactly: OK"}],
    })


# ── Test 5: web_search tool with beta header ──────────────────────────────────

async def test_web_search_with_beta():
    await post(
        {
            "model":    "claude-haiku-4-5-20251001",
            "max_tokens": 200,
            "tools":    [{"type": "web_search_20250305", "name": "web_search"}],
            "messages": [{"role": "user", "content": "Search for: Medlevate startup"}],
        },
        extra_headers={"anthropic-beta": "web-search-2025-03-05"},
    )


# ── Test 6: web_search WITHOUT beta header (Anthropic made it optional) ───────

async def test_web_search_without_beta():
    """Beta header is optional as of 2026-08 — both with and without work."""
    async with httpx.AsyncClient(timeout=15.0) as c:
        resp = await c.post(API_URL, headers=HEADERS_BASE, json={
            "model":    "claude-haiku-4-5-20251001",
            "max_tokens": 200,
            "tools":    [{"type": "web_search_20250305", "name": "web_search"}],
            "messages": [{"role": "user", "content": "Search: Medlevate"}],
        })
    if not resp.is_success:
        raise ValueError(f"HTTP {resp.status_code}: {resp.text[:200]}")


# ── Test 7: sonnet-5 large max_tokens (simulates synthesis call) ─────────────

async def test_sonnet5_large_tokens():
    """Verifies 16000 max_tokens is accepted with thinking disabled."""
    await post({
        "model":      "claude-sonnet-5",
        "max_tokens": 16000,
        "thinking":   {"type": "disabled"},
        "system":     "You are a helpful assistant.",
        "messages":   [{"role": "user", "content": "Reply with exactly: OK"}],
    })


# ── main ──────────────────────────────────────────────────────────────────────

async def main():
    if not API_KEY:
        print("❌ ANTHROPIC_API_KEY not set — set it in .env or environment")
        sys.exit(1)

    print(f"\n🔑 Using key: {API_KEY[:18]}...\n")
    print("Running API call pre-flight checks...\n")

    await check("sonnet-5 with thinking disabled",        test_sonnet5_thinking_disabled())
    await check("opus-5 with thinking disabled",          test_opus5_thinking_disabled())
    await check("haiku-4.5 basic (no temperature)",       test_haiku_basic())
    await check("haiku-4.5 with temperature=0",           test_haiku_with_temperature())
    await check("web_search with beta header",            test_web_search_with_beta())
    await check("web_search without beta (expect fail)",  test_web_search_without_beta())
    await check("sonnet-5 max_tokens=16000",              test_sonnet5_large_tokens())

    passed = sum(1 for _, ok, _ in results if ok)
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")

    if failed:
        print("\nFailed tests:")
        for name, ok, err in results:
            if not ok:
                print(f"  • {name}: {err}")
        sys.exit(1)
    else:
        print("All checks passed — safe to deploy.")


asyncio.run(main())
