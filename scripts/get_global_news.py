#!/usr/bin/env python3
"""Retrieve global / macroeconomic news (Fed, inflation, markets)."""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf
from dateutil.relativedelta import relativedelta

from _common import die, parse_date, yf_retry

QUERIES = [
    "stock market economy",
    "Federal Reserve interest rates",
    "inflation economic outlook",
    "global markets trading",
]


def _extract(article: dict) -> dict:
    if "content" in article:
        c = article["content"]
        url_obj = c.get("canonicalUrl") or c.get("clickThroughUrl") or {}
        pub_date = None
        if c.get("pubDate"):
            try:
                pub_date = datetime.fromisoformat(c["pubDate"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        return {
            "title": c.get("title", "No title"),
            "summary": c.get("summary", ""),
            "publisher": c.get("provider", {}).get("displayName", "Unknown"),
            "link": url_obj.get("url", ""),
            "pub_date": pub_date,
        }
    return {
        "title": article.get("title", "No title"),
        "summary": "",
        "publisher": article.get("publisher", "Unknown"),
        "link": article.get("link", ""),
        "pub_date": None,
    }


def get_global_news(curr_date: str, look_back_days: int, limit: int) -> str:
    curr_dt = parse_date(curr_date)
    start_dt = curr_dt - relativedelta(days=look_back_days)

    seen_titles = set()
    collected = []
    for query in QUERIES:
        search = yf_retry(
            lambda q=query: yf.Search(query=q, news_count=limit, enable_fuzzy_query=True)
        )
        if search.news:
            for article in search.news:
                d = _extract(article)
                if d["title"] and d["title"] not in seen_titles:
                    seen_titles.add(d["title"])
                    collected.append(d)
        if len(collected) >= limit:
            break

    if not collected:
        return f"No global news found for {curr_date}"

    body = ""
    for d in collected[:limit]:
        if d["pub_date"]:
            naive = d["pub_date"].replace(tzinfo=None)
            if naive > curr_dt + relativedelta(days=1):
                continue
        body += f"### {d['title']} (source: {d['publisher']})\n"
        if d["summary"]:
            body += f"{d['summary']}\n"
        if d["link"]:
            body += f"Link: {d['link']}\n"
        body += "\n"

    return (
        f"## Global Market News, from {start_dt.strftime('%Y-%m-%d')} to {curr_date}:\n\n{body}"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--curr-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--look-back", type=int, default=7)
    p.add_argument("--limit", type=int, default=10)
    args = p.parse_args()
    try:
        print(get_global_news(args.curr_date, args.look_back, args.limit))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
