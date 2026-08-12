#!/usr/bin/env python
"""
G.8 — Build the Market Discovery static JSON artifact.

Runs offline (nightly in CI) so the /discovery/opportunities endpoint
can return pre-computed results in <50ms instead of ~25s.

Usage:
    python scripts/build_discovery_index.py [--top-n 1500] [--out app/data/discovery-index.json]

The output file is read by app/api/alignment.py get_opportunities() on every
request. If the file is absent or older than 24 h, the endpoint falls back to
live computation and logs a warning.

Run requirements: DATABASE_URL and ANTHROPIC_API_KEY must be set (same as
the Railway environment). The script completes in ~25-60s depending on DB
latency and universe size.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import pathlib
import sys
import time
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("build_discovery_index")

# Default output path (relative to project root)
_PROJECT_ROOT = pathlib.Path(__file__).parent.parent
_DEFAULT_OUT  = _PROJECT_ROOT / "app" / "data" / "discovery-index.json"


async def _build(top_n: int, out_path: pathlib.Path) -> None:
    logger.info("Building discovery index (top_n=%d) → %s", top_n, out_path)
    t0 = time.time()

    from app.services.opportunity_scorer_v2 import run_discovery_engine_v2
    opportunities = await run_discovery_engine_v2(top_n=top_n)

    if not opportunities:
        logger.error("run_discovery_engine_v2 returned empty list — aborting")
        sys.exit(1)

    # Try universe size
    universe_size = top_n
    try:
        from app.services.universe_expander_v2 import get_all_diseases_for_batch_scoring
        universe_size = len(get_all_diseases_for_batch_scoring())
    except Exception:
        universe_size = len(opportunities)

    payload = {
        "opportunities": opportunities,
        "universe_size":  universe_size,
        "total_scored":   len(opportunities),
        "algorithm":      f"Static build — {len(opportunities):,} diseases",
        "built_at":       datetime.now(timezone.utc).isoformat(),
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "top50":          opportunities[:50],   # inlined for immediate first paint
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, default=str)

    # Write main file
    out_path.write_text(body, encoding="utf-8")
    logger.info("Wrote %d bytes to %s", len(body), out_path)

    # Content-addressed copy for cache-busting (first 8 chars of SHA-256)
    digest = hashlib.sha256(body.encode()).hexdigest()[:8]
    addressed = out_path.parent / f"discovery-index-{digest}.json"
    addressed.write_text(body, encoding="utf-8")
    logger.info("Content-addressed copy: %s", addressed)

    elapsed = time.time() - t0
    logger.info(
        "Done: %d opportunities, universe_size=%d, elapsed=%.1fs",
        len(opportunities), universe_size, elapsed,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Market Discovery static JSON index")
    parser.add_argument("--top-n", type=int, default=1500, help="Max diseases to score")
    parser.add_argument("--out",   type=pathlib.Path, default=_DEFAULT_OUT,
                        help="Output path for discovery-index.json")
    args = parser.parse_args()

    # Ensure project root is on sys.path so app.* imports work
    sys.path.insert(0, str(_PROJECT_ROOT))

    asyncio.run(_build(args.top_n, args.out))


if __name__ == "__main__":
    main()
