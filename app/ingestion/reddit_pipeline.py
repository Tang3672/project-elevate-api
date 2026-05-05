"""
Reddit Ingestion Pipeline
Scrapes healthcare subreddits, filters pain points, classifies and stores as hospital needs.
"""
import asyncio
import logging
from dataclasses import dataclass
from typing import List

from app.ingestion.connectors.reddit_scraper import (
    RedditScraper, is_pain_point, extract_department_hint
)
from app.services.classification_service import classify_need
from app.services.embedding_service import embed_text
from app.db.needs_repository import insert_need

logger = logging.getLogger(__name__)


@dataclass
class RedditIngestionResult:
    subreddits_scraped: int
    posts_fetched:      int
    pain_points_found:  int
    inserted:           int
    skipped_duplicate:  int
    errors:             int


async def run_reddit_ingestion(
    subreddits=None,
    max_per_subreddit=50,
    dry_run=False,
):
    scraper = RedditScraper()
    result  = RedditIngestionResult(
        subreddits_scraped=len(subreddits or [9]),
        posts_fetched=0, pain_points_found=0,
        inserted=0, skipped_duplicate=0, errors=0)

    try:
        posts = await scraper.scrape_pain_points(
            subreddits=subreddits,
            max_per_subreddit=max_per_subreddit)
        result.posts_fetched = len(posts)
    except Exception as e:
        logger.error(f"Reddit scrape failed: {e}")
        return result

    pain_points = [p for p in posts if is_pain_point(p.full_text)]
    result.pain_points_found = len(pain_points)
    logger.info(f"Filtered to {len(pain_points)} pain points from {len(posts)} posts")

    for post in pain_points:
        try:
            raw_text = post.full_text[:2000]
            if len(raw_text) < 50:
                continue

            classified = await classify_need(raw_text)
            embedding  = await embed_text(raw_text)

            if dry_run:
                logger.info(
                    f"[DRY RUN] r/{post.subreddit}: "
                    f"{post.title[:60]} -> "
                    f"{classified.department}/{classified.category} "
                    f"urgency={classified.urgency_score}"
                )
                result.inserted += 1
                await asyncio.sleep(0.3)
                continue

            # Call insert_need with the original positional signature
            await insert_need(
                raw_text             = raw_text,
                department           = classified.department,
                category             = classified.category,
                subcategory          = getattr(classified, 'subcategory', ''),
                urgency_score        = classified.urgency_score,
                patient_impact_score = classified.patient_impact_score,
                keywords             = classified.keywords,
                embedding            = embedding,
                hospital_id          = post.url,
                submitted_by         = f"r/{post.subreddit}",
                source               = "reddit",
            )
            result.inserted += 1
            await asyncio.sleep(0.5)

        except Exception as e:
            logger.warning(f"Failed to process {post.reddit_id}: {e}")
            result.errors += 1

    logger.info(
        f"Reddit ingestion: {result.inserted} inserted, "
        f"{result.skipped_duplicate} duplicates, "
        f"{result.errors} errors"
    )
    return result
