#!/usr/bin/env python3
"""Retrieve global / macroeconomic news (central banks, growth, rates, geopolitics, commodities).

Google News RSS comes first: each topic is searched within the window itself, so a
past-dated run gets the macro news of its own week. When Google fails or finds
nothing, Yahoo Finance search is tried; it serves only recent items.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf
from dateutil.relativedelta import relativedelta

import _google_news
from _common import coverage_gap, die, extract_article, format_articles, in_window, parse_date, yf_retry

GOOGLE_TOPICS = [
    '"Federal Reserve" OR FOMC OR "interest rates"',
    'inflation OR CPI OR "jobs report" OR payrolls OR GDP',
    '"Treasury yields" OR "bond market" OR "dollar index"',
    '"stock market" OR "S&P 500" OR "Wall Street" OR Nasdaq',
    'tariffs OR sanctions OR geopolitical OR "trade war"',
    'ECB OR "Bank of England" OR "Bank of Japan" OR "China economy"',
    'oil OR OPEC OR commodities OR gold',
]

# Yahoo search only matches short terms: multi-word queries return nothing, and
# fuzzy matching returns unrelated latest news. Index and futures symbols pull in
# the articles Yahoo tags with them (market wraps, oil).
YAHOO_QUERIES = [
    "^GSPC",
    "Federal Reserve",
    "inflation",
    "Treasury yields",
    "jobs report",
    "ECB",
    "tariffs",
    "CL=F",
    "recession",
    "geopolitical",
]
YAHOO_PER_QUERY = 8


def round_robin(per_topic: list[list[dict]], limit: int) -> list[dict]:
    """Take each topic's best article in turn, so one busy topic cannot fill the limit."""
    seen, chosen = set(), []
    for rank in range(max((len(a) for a in per_topic), default=0)):
        for articles in per_topic:
            if rank < len(articles) and articles[rank]["title"] not in seen:
                seen.add(articles[rank]["title"])
                chosen.append(articles[rank])
    return chosen[:limit]


def from_google(start_date: str, curr_date: str, limit: int) -> str | None:
    per_topic, failures = [], []
    for topic in GOOGLE_TOPICS:
        try:
            per_topic.append(_google_news.search(topic, start_date, curr_date))
        except _google_news.GoogleNewsError as exc:
            failures.append(f"{topic}: {exc}")
    if failures:
        print(f"[warn] Google News failed for {len(failures)} topics: {'; '.join(failures)}", file=sys.stderr)
    chosen = round_robin(per_topic, limit)
    if not chosen:
        return None
    chosen.sort(key=lambda a: a["pub_date"], reverse=True)
    return (f"## Global Market News, from {start_date} to {curr_date} — source: Google News, "
            f"{len(chosen)} headlines across {len(per_topic)} macro topics (no article text):\n\n"
            f"{format_articles(chosen)}")


def from_yahoo(start_dt, curr_dt, start_date: str, curr_date: str, limit: int) -> str:
    per_query = []
    for query in YAHOO_QUERIES:
        found = yf_retry(
            lambda q=query: yf.Search(query=q, news_count=YAHOO_PER_QUERY, enable_fuzzy_query=False).news
        )
        # Window first: an out-of-window article must not use up the limit.
        articles = [extract_article(a) for a in found or []]
        per_query.append([a for a in articles if in_window(a["pub_date"], start_dt, curr_dt)])

    chosen = round_robin(per_query, limit)
    if not chosen:
        gap = coverage_gap((), start_date, curr_date, "Global news", "market news")
        return gap or f"No global news found between {start_date} and {curr_date}"
    return (f"## Global Market News, from {start_date} to {curr_date} — source: Yahoo Finance search:\n\n"
            f"{format_articles(chosen)}")


def get_global_news(curr_date: str, look_back_days: int, limit: int) -> str:
    curr_dt = parse_date(curr_date)
    start_dt = curr_dt - relativedelta(days=look_back_days)
    start_date = start_dt.strftime("%Y-%m-%d")
    return (from_google(start_date, curr_date, limit)
            or from_yahoo(start_dt, curr_dt, start_date, curr_date, limit))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--curr-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--look-back", type=int, default=7)
    p.add_argument("--limit", type=int, default=15)
    args = p.parse_args()
    try:
        print(get_global_news(args.curr_date, args.look_back, args.limit))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
