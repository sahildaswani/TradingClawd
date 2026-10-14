#!/usr/bin/env python3
"""Retrieve recent Reddit posts mentioning a ticker, from Reddit's public RSS search feed.

No login or API key. Reddit's JSON endpoints return 403 to anonymous clients; the
RSS feed still serves them, but allows about one request per minute per IP and
carries no vote or comment counts. All subreddits are searched in one combined
request. Calls from agents running in parallel queue on a lock in the TradingClawd
cache directory, so each waits for Reddit's rate-limit window instead of failing.

A failed fetch is reported as unavailable, never as "no posts": the two are
different claims, and the sentiment analyst must not read silence that was never
observed.
"""

import argparse
import fcntl
import html
import http.client
import os
import random
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import UTC, coverage_gap, die, in_window, parse_date

RSS = "https://www.reddit.com/r/{subs}/search.rss?{qs}"
# Reddit blocks generic user agents; an identified one is served.
UA = "tradingclawd/0.5 (+https://github.com/sahildaswani/TradingClawd)"
ATOM = {"atom": "http://www.w3.org/2005/Atom"}

STOCK_SUBREDDITS = ("wallstreetbets", "stocks", "investing")
CRYPTO_SUBREDDITS = ("CryptoCurrency", "CryptoMarkets")
COIN_SUBREDDITS = {"BTC": "Bitcoin", "ETH": "ethereum", "SOL": "solana"}
CRYPTO_QUOTES = ("-USD", "-USDT", "-USDC")

FEED_PAGE = 100                       # Reddit's maximum page size
SEARCH_LOOKBACK = timedelta(days=7)   # matches t=week
MAX_QUEUE_SECONDS = 300               # give up rather than wait longer than this for a turn
MAX_BYTES = 5 * 1024 * 1024

STATE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "tradingclawd")
LOCK_PATH = os.path.join(STATE_DIR, "reddit.lock")
NEXT_OK_PATH = os.path.join(STATE_DIR, "reddit_next_ok")


def crypto_base(ticker: str) -> str | None:
    t = ticker.upper()
    for quote in CRYPTO_QUOTES:
        if t.endswith(quote):
            return t[: -len(quote)]
    return None


def subreddits_for(ticker: str) -> tuple[str, ...]:
    base = crypto_base(ticker)
    if not base:
        return STOCK_SUBREDDITS
    coin = COIN_SUBREDDITS.get(base)
    return ((coin,) if coin else ()) + CRYPTO_SUBREDDITS


# --- Rate-limit queue ------------------------------------------------------------


def _read_next_ok() -> float:
    try:
        with open(NEXT_OK_PATH) as f:
            return float(f.read().strip() or 0)
    except (OSError, ValueError):
        return 0.0


def _write_next_ok(epoch: float) -> None:
    with open(NEXT_OK_PATH, "w") as f:
        f.write(f"{epoch:.0f}")


def _wait_seconds(headers) -> float:
    """Seconds until Reddit allows the next request, from its rate-limit headers."""
    try:
        remaining = float(headers.get("x-ratelimit-remaining", "1"))
        reset = float(headers.get("x-ratelimit-reset", "60"))
    except (TypeError, ValueError):
        return 60.0
    return reset + 1 if remaining < 1 else 1.0


def _fetch_feed(query: str, subs: str) -> tuple[bytes | None, str]:
    """One RSS request, taking its turn in the cross-process queue. Returns (body, error)."""
    os.makedirs(STATE_DIR, exist_ok=True)
    url = RSS.format(subs=subs, qs=urlencode({
        "q": query, "restrict_sr": "on", "sort": "new", "t": "week", "limit": FEED_PAGE,
    }))
    deadline = time.time() + MAX_QUEUE_SECONDS
    with open(LOCK_PATH, "a") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.time() > deadline:
                    return None, "rate-limit queue wait exceeded"
                time.sleep(1 + random.random())
        try:
            for attempt in range(3):
                wait = _read_next_ok() - time.time()
                if wait > 0:
                    if time.time() + wait > deadline:
                        return None, "rate-limit queue wait exceeded"
                    time.sleep(wait)
                try:
                    with urlopen(Request(url, headers={"User-Agent": UA}), timeout=20) as resp:
                        body = resp.read(MAX_BYTES + 1)
                        _write_next_ok(time.time() + _wait_seconds(resp.headers))
                    if len(body) > MAX_BYTES:
                        return None, "feed exceeded size limit"
                    return body, ""
                except HTTPError as exc:
                    if exc.code == 429 and attempt < 2:
                        _write_next_ok(time.time() + _wait_seconds(exc.headers or {}))
                        continue
                    _write_next_ok(time.time() + 60)
                    return None, f"HTTP {exc.code}"
                except (OSError, http.client.HTTPException) as exc:
                    return None, str(exc)
            return None, "HTTP 429 after retries"
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


# --- Parsing and output ----------------------------------------------------------


def _strip_html(content: str) -> str:
    if not content:
        return ""
    if "<!-- SC_OFF -->" in content and "<!-- SC_ON -->" in content:
        content = content.split("<!-- SC_OFF -->")[1].split("<!-- SC_ON -->")[0]
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", content)).split())


def _parse(body: bytes) -> list[dict]:
    posts = []
    for entry in ET.fromstring(body).findall("atom:entry", ATOM):
        title = entry.find("atom:title", ATOM)
        published = entry.find("atom:published", ATOM)
        content = entry.find("atom:content", ATOM)
        category = entry.find("atom:category", ATOM)
        link = entry.find("atom:link", ATOM)
        when = None
        if published is not None and published.text:
            try:
                when = datetime.fromisoformat(published.text.replace("Z", "+00:00"))
            except ValueError:
                pass
        posts.append({
            "title": " ".join(((title.text if title is not None else "") or "").split()),
            "published": when,
            "body": _strip_html(content.text if content is not None else ""),
            "subreddit": category.get("term") if category is not None else "",
            "link": link.get("href") if link is not None else "",
        })
    return posts


def get_reddit(ticker: str, start_date: str, end_date: str, per_sub: int = 8, company: str = "") -> str:
    subreddits = subreddits_for(ticker)
    query = crypto_base(ticker) or ticker.upper()
    label = ", ".join(f"r/{s}" for s in subreddits)
    # Posters write the company name as often as the ticker; searching both in the
    # same request costs no extra rate-limit turn.
    search = f'{query} OR "{company}"' if company else query

    body, error = _fetch_feed(search, "+".join(subreddits))
    if body is None:
        return f"<Reddit unavailable ({label}): {error}; this is not an absence of discussion>"
    try:
        fetched = _parse(body)
    except ET.ParseError as exc:
        return f"<Reddit unavailable ({label}): unreadable feed ({exc}); this is not an absence of discussion>"

    start_dt, end_dt = parse_date(start_date), parse_date(end_date)
    posts = [p for p in fetched if in_window(p["published"], start_dt, end_dt)]
    if not posts:
        dates = [p["published"] for p in fetched]
        if len(fetched) < FEED_PAGE:
            dates.append(datetime.now(UTC) - SEARCH_LOOKBACK)
        gap = coverage_gap(dates, start_date, end_date, "Reddit search", f"discussion of {query}")
        return gap or f"<no Reddit posts mentioning {query} across {label} within {start_date}..{end_date}>"

    by_sub = {s.lower(): (s, []) for s in subreddits}
    for p in posts:
        name = p["subreddit"] or "unknown"
        by_sub.setdefault(name.lower(), (name, []))[1].append(p)

    page_full = len(fetched) >= FEED_PAGE
    blocks = [f"# Reddit posts mentioning {search}, {start_date} to {end_date} "
              f"(RSS search across {label}; no vote or comment counts)"]
    for sub, sub_posts in by_sub.values():
        if not sub_posts:
            blocks.append(f"r/{sub}: <not among the newest {FEED_PAGE} matches across {label}>"
                          if page_full else f"r/{sub}: <no posts mentioning {query}>")
            continue
        lines = [f"## r/{sub} — {len(sub_posts)} posts in window, newest {min(per_sub, len(sub_posts))} shown"]
        for p in sub_posts[:per_sub]:
            when = f"{p['published']:%Y-%m-%d}" if p["published"] else "?"
            lines.append(f"- [{when}] {p['title']}")
            if p["body"]:
                excerpt = p["body"] if len(p["body"]) <= 300 else p["body"][:300] + "…"
                lines.append(f"  body: {excerpt}")
            if p["link"]:
                lines.append(f"  link: {p['link']}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticker", required=True)
    p.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, help="YYYY-MM-DD (inclusive)")
    p.add_argument("--company", default="", help='company name to search alongside the ticker, e.g. "Nvidia"')
    p.add_argument("--per-sub", type=int, default=8, help="max posts shown per subreddit")
    args = p.parse_args()
    try:
        print(get_reddit(args.ticker, args.start_date, args.end_date, args.per_sub, args.company))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
