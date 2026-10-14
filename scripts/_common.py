"""Shared utilities for TradingClawd data scripts."""

import contextlib
import logging
import sys
import time
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc  # datetime.UTC only exists from Python 3.11

logger = logging.getLogger(__name__)


def yf_retry(func, max_retries=3, base_delay=2.0):
    """Execute a yfinance call with exponential backoff on rate limits."""
    from yfinance.exceptions import YFRateLimitError

    for attempt in range(max_retries + 1):
        try:
            return func()
        except YFRateLimitError:
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                print(
                    f"[warn] Yahoo Finance rate-limited, retrying in {delay:.0f}s "
                    f"(attempt {attempt + 1}/{max_retries})",
                    file=sys.stderr,
                )
                time.sleep(delay)
            else:
                raise


def parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def next_day(s: str) -> str:
    """The day after ``s`` (YYYY-MM-DD). yfinance treats ``end`` as exclusive, so a
    fetch that must include ``s`` asks for the day after it."""
    return (parse_date(s) + timedelta(days=1)).strftime("%Y-%m-%d")


def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def die(msg: str, code: int = 1):
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(code)


# --- Point-in-time windows -------------------------------------------------------
# Dated items (news, Reddit posts) are kept when published in the half-open UTC
# window [start, end + 1 day). An undated item is kept only when the window reaches
# the present, since a past-dated run cannot prove it is not from after its date.


def to_utc(dt: datetime) -> datetime:
    """Normalize a datetime to UTC-aware; a naive value is assumed to be UTC."""
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def in_window(pub_dt: datetime | None, start_dt: datetime, end_dt: datetime) -> bool:
    end = to_utc(end_dt)
    if pub_dt is not None:
        return to_utc(start_dt) <= to_utc(pub_dt) < end + timedelta(days=1)
    return end >= datetime.now(UTC) - timedelta(days=1)


def coverage_gap(dates, start_date: str, end_date: str, source: str, subject: str) -> str | None:
    """A placeholder for a window the feed did not observe, or None when it did.

    Yahoo news and Reddit search serve their latest items whatever window is asked
    for, so "nothing found" over a window they never reached would claim an absence
    nobody saw. ``dates`` are the returned items' timestamps (plus a fixed lookback
    start, for a feed that has one); the oldest bounds what the feed covered.
    """
    now = datetime.now(UTC)
    oldest = min((to_utc(d) for d in dates if d is not None), default=now)
    if parse_date(end_date).date() > now.date():
        reason = "the window extends past today"
    elif oldest.date() > parse_date(start_date).date():
        reason = "it only serves recent items"
    else:
        return None
    return f"<{source} unavailable for {start_date}..{end_date}: {reason}, so this is not an absence of {subject}>"


def is_historical(run_date: str | None) -> bool:
    """Whether a run is dated before today."""
    return bool(run_date) and run_date < date.today().strftime("%Y-%m-%d")


# --- Yahoo Finance news ----------------------------------------------------------


def extract_article(article: dict) -> dict:
    """Title, summary, publisher, link and UTC publish time of a Yahoo news item.

    Handles both the nested ``content`` shape and the flat shape Yahoo search
    returns. Yahoo sends some fields as null rather than leaving them out, so each
    falls back to its default on a null as well as a missing key.
    """
    content = article.get("content")
    if isinstance(content, dict):
        url_obj = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        pub_date = None
        if content.get("pubDate"):
            with contextlib.suppress(ValueError, AttributeError):
                pub_date = datetime.fromisoformat(content["pubDate"].replace("Z", "+00:00"))
        return {
            "title": content.get("title") or "No title",
            "summary": content.get("summary") or "",
            "publisher": (content.get("provider") or {}).get("displayName") or "Unknown",
            "link": url_obj.get("url") or "",
            "pub_date": pub_date,
        }
    pub_date = None
    ts = article.get("providerPublishTime")
    if ts:
        with contextlib.suppress(ValueError, OSError, TypeError):
            pub_date = datetime.fromtimestamp(ts, tz=UTC)
    return {
        "title": article.get("title") or "No title",
        "summary": article.get("summary") or "",
        "publisher": article.get("publisher") or "Unknown",
        "link": article.get("link") or "",
        "pub_date": pub_date,
    }


def format_articles(articles: list[dict]) -> str:
    out = ""
    for a in articles:
        published = f", {a['pub_date']:%Y-%m-%d}" if a["pub_date"] else ""
        out += f"### {a['title']} (source: {a['publisher']}{published})\n"
        if a["summary"]:
            out += f"{a['summary']}\n"
        if a["link"]:
            out += f"Link: {a['link']}\n"
        out += "\n"
    return out
