import asyncio
import logging
import time
from typing import List, Optional
from dataclasses import dataclass
import httpx

logger = logging.getLogger(__name__)

REDDIT_BASE = "https://www.reddit.com"
USER_AGENT  = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

TARGET_SUBREDDITS = [
    "nursing", "medicine", "emergencymedicine", "pharmacy",
    "residency", "hospitalist", "InfectiousDisease", "Noctor",
]

PAIN_POINT_QUERIES = [
    "we need a better",
    "frustrated with",
    "patient safety problem",
    "medication error",
    "antibiotic resistance",
    "workflow problem",
    "drug shortage",
]


@dataclass
class RedditPost:
    reddit_id:   str
    subreddit:   str
    title:       str
    body:        str
    author:      str
    score:       int
    url:         str
    created_utc: float
    post_type:   str = "post"

    @property
    def full_text(self):
        return f"{self.title}\n\n{self.body}".strip()

    @property
    def is_quality(self):
        text = self.full_text
        if self.score < 3 or len(text) < 80:
            return False
        bads = ["[deleted]", "[removed]", "shitpost", "meme", "weekly thread", "mod post"]
        return not any(b in text.lower() for b in bads)


class RedditScraper:

    def __init__(self):
        self._last_request = 0.0

    async def _get(self, url, params=None):
        elapsed = time.time() - self._last_request
        if elapsed < 3.0:
            await asyncio.sleep(3.0 - elapsed)
        self._last_request = time.time()

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                r = await client.get(
                    url, params=params or {},
                    headers={"User-Agent": USER_AGENT},
                    follow_redirects=True,
                )
                if r.status_code == 429:
                    logger.warning("Rate limited — sleeping 30s")
                    await asyncio.sleep(30)
                    r = await client.get(
                        url, params=params or {},
                        headers={"User-Agent": USER_AGENT},
                        follow_redirects=True,
                    )
                r.raise_for_status()
                return r.json()
        except Exception as e:
            logger.warning(f"Request failed {url}: {e}")
            return {"data": {"children": []}}

    def _parse_posts(self, data, subreddit):
        posts = []
        for child in data.get("data", {}).get("children", []):
            pd = child.get("data", {})
            if not pd.get("is_self"):
                continue
            post = RedditPost(
                reddit_id=pd.get("id", ""), subreddit=subreddit,
                title=pd.get("title", ""), body=pd.get("selftext", ""),
                author=pd.get("author", "[deleted]"), score=pd.get("score", 0),
                url=f"https://reddit.com{pd.get('permalink', '')}",
                created_utc=pd.get("created_utc", 0),
            )
            if post.is_quality:
                posts.append(post)
        return posts

    async def search_subreddit(self, subreddit, query, limit=5):
        data = await self._get(f"{REDDIT_BASE}/r/{subreddit}/search.json", {
            "q": query, "restrict_sr": "1",
            "sort": "relevance", "t": "year", "limit": str(limit),
        })
        return self._parse_posts(data, subreddit)

    async def get_top_posts(self, subreddit, limit=25):
        data = await self._get(f"{REDDIT_BASE}/r/{subreddit}/top.json",
                               {"limit": str(limit), "t": "month"})
        return self._parse_posts(data, subreddit)

    async def scrape_pain_points(self, subreddits=None, max_per_subreddit=30):
        if subreddits is None:
            subreddits = TARGET_SUBREDDITS

        all_posts = {}

        for idx, subreddit in enumerate(subreddits):
            logger.info(f"Scraping r/{subreddit} ({idx+1}/{len(subreddits)})...")
            count = 0

            top = await self.get_top_posts(subreddit, limit=min(max_per_subreddit, 25))
            for post in top:
                if post.reddit_id not in all_posts:
                    all_posts[post.reddit_id] = post
                    count += 1

            for query in PAIN_POINT_QUERIES:
                if count >= max_per_subreddit:
                    break
                results = await self.search_subreddit(subreddit, query, limit=5)
                for post in results:
                    if post.reddit_id not in all_posts:
                        all_posts[post.reddit_id] = post
                        count += 1

            logger.info(f"r/{subreddit}: {count} collected")
            await asyncio.sleep(5)

        logger.info(f"Total: {len(all_posts)} unique posts")
        return list(all_posts.values())


def is_pain_point(text):
    text_lower = text.lower()
    pain = [
        "we need", "we don't have", "frustrated", "wish", "problem",
        "error", "fail", "broken", "shortage", "can't", "cannot",
        "dangerous", "unsafe", "risk", "harm", "missed", "delayed",
        "workaround", "doesn't work",
    ]
    clinical = [
        "patient", "hospital", "icu", "ed ", "er ", "nursing",
        "physician", "doctor", "nurse", "pharmacist", "medication",
        "drug", "antibiotic", "device", "treatment", "infection",
        "sepsis", "handoff", "shift", "discharge", "formulary",
        "ehr", "emr", "dose", "chart", "order",
    ]
    return (any(p in text_lower for p in pain) and
            any(c in text_lower for c in clinical))


def extract_department_hint(text):
    text_lower = text.lower()
    depts = {
        "ICU":       ["icu", "intensive care", "critical care"],
        "Emergency": ["ed ", "er ", "emergency department"],
        "Pharmacy":  ["pharmacist", "pharmacy", "formulary"],
        "Nursing":   ["nurse", "nursing", "rn "],
        "Surgery":   ["surgery", "operating room"],
        "ID":        ["infectious disease", "antibiotic", "sepsis"],
    }
    for dept, patterns in depts.items():
        if any(p in text_lower for p in patterns):
            return dept
    return None
