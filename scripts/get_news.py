#!/usr/bin/env python3
"""Retrieve recent news headlines for a ticker over a date range."""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf
from dateutil.relativedelta import relativedelta

from _common import die, parse_date, yf_retry


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
        "summary": article.get("summary", ""),
        "publisher": article.get("publisher", "Unknown"),
        "link": article.get("link", ""),
        "pub_date": None,
    }


def get_news(ticker: str, start_date: str, end_date: str) -> str:
    start_dt = parse_date(start_date)
    end_dt = parse_date(end_date)

    stock = yf.Ticker(ticker.upper())
    news = yf_retry(lambda: stock.get_news(count=20))
    if not news:
        return f"No news found for {ticker}"

    body = ""
    count = 0
    for article in news:
        d = _extract(article)
        if d["pub_date"]:
            naive = d["pub_date"].replace(tzinfo=None)
            if not (start_dt <= naive <= end_dt + relativedelta(days=1)):
                continue
        body += f"### {d['title']} (source: {d['publisher']})\n"
        if d["summary"]:
            body += f"{d['summary']}\n"
        if d["link"]:
            body += f"Link: {d['link']}\n"
        body += "\n"
        count += 1

    if count == 0:
        return f"No news found for {ticker} between {start_date} and {end_date}"
    return f"## {ticker} News, from {start_date} to {end_date}:\n\n{body}"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticker", required=True)
    p.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    args = p.parse_args()
    try:
        print(get_news(args.ticker, args.start_date, args.end_date))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
