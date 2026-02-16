from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import httpx


class RedditSocialError(RuntimeError):
    pass


_CASHTAG_RE = re.compile(r"\$([A-Z]{1,5})(?:\b|$)")
_PLAIN_TICKER_RE = re.compile(r"(?<![A-Z])([A-Z]{2,5})(?![A-Z])")
_STOPWORDS = {
    "A",
    "AI",
    "ALL",
    "AND",
    "ARE",
    "CEO",
    "CFO",
    "CTO",
    "DD",
    "ETF",
    "FOR",
    "FOMO",
    "HODL",
    "IMO",
    "IRS",
    "IT",
    "IV",
    "M&A",
    "MRNA",
    "NOT",
    "NOW",
    "OF",
    "ON",
    "OR",
    "OTM",
    "PM",
    "PSA",
    "SEC",
    "THE",
    "TO",
    "USA",
    "USD",
    "YOLO",
}


def _bucket_floor(dt: datetime, minutes: int) -> datetime:
    if minutes <= 0:
        return dt.replace(second=0, microsecond=0)
    base = dt.replace(second=0, microsecond=0)
    floored = (base.minute // minutes) * minutes
    return base.replace(minute=floored)


def extract_tickers_from_text(text: str, *, allow_plain_upper: bool = False) -> set[str]:
    """
    Extract probable tickers from social text.

    Defaults to strict cashtag mode (e.g. $AAPL) to avoid false positives.
    Optional plain-uppercase mode can be enabled for broader recall.
    """

    if not text:
        return set()

    out = {m.group(1).upper() for m in _CASHTAG_RE.finditer(text)}
    if not allow_plain_upper:
        return out

    for m in _PLAIN_TICKER_RE.finditer(text):
        t = m.group(1).upper()
        if t in _STOPWORDS:
            continue
        out.add(t)
    return out


@dataclass(frozen=True)
class RedditTickerBucket:
    ticker: str
    bucket_start: datetime
    mentions: int
    sentiment_hint: Optional[float]
    source: str
    bucket_minutes: int


@dataclass
class RedditSocialClient:
    user_agent: str = "WealthPulse social listener (contact@example.com)"
    timeout_s: float = 20.0
    rps: float = 1.0
    _last_request_at: float = 0.0

    def _sleep_for_rate_limit(self) -> None:
        if self.rps <= 0:
            return
        min_interval = 1.0 / self.rps
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def fetch_listing(self, *, subreddit: str, listing: str = "new", limit: int = 100) -> dict:
        sub = subreddit.strip().lower()
        if not sub:
            raise RedditSocialError("empty subreddit")
        list_name = listing.strip().lower() or "new"
        if list_name not in {"new", "hot"}:
            raise RedditSocialError("listing must be new|hot")
        lim = max(1, min(int(limit or 100), 100))

        url = f"https://www.reddit.com/r/{sub}/{list_name}.json?limit={lim}"
        self._sleep_for_rate_limit()
        self._last_request_at = time.monotonic()
        try:
            resp = httpx.get(
                url,
                timeout=self.timeout_s,
                headers={"User-Agent": self.user_agent, "Accept": "application/json"},
            )
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise RedditSocialError(f"Reddit request failed for r/{sub}: {e}") from e

        try:
            return json.loads(resp.text)
        except Exception as e:
            raise RedditSocialError(f"Invalid Reddit JSON for r/{sub}: {e}") from e


def parse_reddit_listing_to_buckets(
    *,
    payload: dict,
    source: str,
    bucket_minutes: int = 15,
    since: Optional[datetime] = None,
    allow_plain_upper: bool = False,
) -> list[RedditTickerBucket]:
    """
    Convert Reddit listing payload into per-ticker mention buckets.
    """

    children = (((payload or {}).get("data") or {}).get("children") or [])
    bucket_counts: dict[tuple[str, datetime], int] = {}

    for ch in children:
        data = (ch or {}).get("data") or {}
        created_utc = data.get("created_utc")
        if created_utc is None:
            continue
        try:
            created_dt = datetime.fromtimestamp(float(created_utc), tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            continue
        if since is not None and created_dt < since:
            continue

        text = " ".join(
            [
                str(data.get("title") or ""),
                str(data.get("selftext") or ""),
            ]
        ).strip()
        tickers = extract_tickers_from_text(text, allow_plain_upper=allow_plain_upper)
        if not tickers:
            continue

        bucket = _bucket_floor(created_dt, minutes=bucket_minutes)
        for t in tickers:
            key = (t, bucket)
            bucket_counts[key] = bucket_counts.get(key, 0) + 1

    out: list[RedditTickerBucket] = []
    for (ticker, bucket_start), mentions in bucket_counts.items():
        out.append(
            RedditTickerBucket(
                ticker=ticker,
                bucket_start=bucket_start,
                mentions=int(mentions),
                sentiment_hint=None,
                source=source,
                bucket_minutes=bucket_minutes,
            )
        )
    return sorted(out, key=lambda r: (r.ticker, r.bucket_start), reverse=True)
