#!/usr/bin/env python3
"""Retrieve news about a ticker published within a date range.

Google News RSS comes first: it searches the company name and ticker within the
window itself, so a past-dated run gets the news of its own week. When Google
fails or finds nothing, Yahoo Finance is tried: the symbol's quote feed, then
Yahoo search's articles tagged with the symbol (the quote feed has been returning
nothing). Yahoo serves only recent items, so a source that could not answer is
reported as unavailable, which is not the same claim as there being no news.
"""

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf

import _google_news
from _common import coverage_gap, die, extract_article, format_articles, in_window, parse_date, yf_retry

CRYPTO_QUOTES = ("-USD", "-USDT", "-USDC")
# Legal and listing suffixes nobody writes in a headline: "NVIDIA Corporation" -> "NVIDIA".
NAME_SUFFIX = re.compile(
    r"[,\s]+(inc\.?|incorporated|corp\.?|corporation|co\.?|company|ltd\.?|limited|plc|s\.a\.|sa|ag|"
    r"n\.v\.|nv|se|holdings?|group|usd|new|class [a-z]|cl [a-z])$",
    re.IGNORECASE,
)


def short_name(name: str) -> str:
    previous = None
    while previous != name:
        previous, name = name, NAME_SUFFIX.sub("", name).strip()
    return name


def resolve_company(symbol: str) -> str:
    """The company's short name from Yahoo's quote search, or "" when unknown."""
    try:
        search = yf_retry(lambda: yf.Search(symbol, news_count=0, max_results=5))
    except Exception:
        return ""
    for q in (search.quotes if search else None) or []:
        if (q.get("symbol") or "").upper() == symbol:
            return short_name(q.get("shortname") or q.get("longname") or "")
    return ""


def google_query(symbol: str, company: str) -> str:
    # Quote each term: a bare "BTC-USD" or "BRK-B" reads as an exclusion to Google.
    term = symbol
    for quote_ccy in CRYPTO_QUOTES:
        if symbol.endswith(quote_ccy):
            term = symbol[: -len(quote_ccy)]
    terms = [f'"{company}"'] if company and company.upper() != term else []
    return " OR ".join(terms + [f'"{term}"'])


def from_google(symbol: str, company: str, start_date: str, end_date: str, limit: int) -> str | None:
    query = google_query(symbol, company)
    try:
        articles = _google_news.search(query, start_date, end_date)
    except _google_news.GoogleNewsError as exc:
        print(f"[warn] Google News failed for {query}: {exc}; trying Yahoo Finance", file=sys.stderr)
        return None
    if not articles:
        return None
    # Keep Google's most relevant items, then show them newest first.
    chosen = sorted(articles[:limit], key=lambda a: a["pub_date"], reverse=True)
    return (f"## {symbol} News, from {start_date} to {end_date} — source: Google News search "
            f"for {query}, {len(chosen)} of {len(articles)} headlines (no article text):\n\n"
            f"{format_articles(chosen)}")


def _search_news(symbol: str, limit: int) -> tuple[list, bool]:
    """Yahoo search's articles tagged with ``symbol``, and whether search answered.

    Search results are a relevance-picked sample and some are tagged loosely, so
    only articles whose related tickers include the symbol are kept.
    """
    search = yf_retry(lambda: yf.Search(symbol, news_count=limit))
    if search is None:
        return [], False
    tagged = [
        a for a in (search.news or [])
        if symbol in (t.upper() for t in a.get("relatedTickers") or [])
    ]
    knows = any((q.get("symbol") or "").upper() == symbol for q in search.quotes or [])
    return tagged, knows or bool(search.news)


def from_yahoo(symbol: str, start_date: str, end_date: str, limit: int) -> str:
    start_dt, end_dt = parse_date(start_date), parse_date(end_date)

    feed = yf_retry(lambda: yf.Ticker(symbol).get_news(count=limit)) or []
    from_search = not feed
    if from_search:
        found, answered = _search_news(symbol, limit)
        if not answered or not found:
            return (f"<News unavailable for {symbol}: Google News found nothing, the Yahoo quote feed "
                    f"returned nothing and Yahoo search has no articles tagged {symbol}, so this is "
                    f"not an absence of news>")
        articles = [extract_article(a) for a in found]
    else:
        articles = [extract_article(a) for a in feed]

    in_range = [a for a in articles if in_window(a["pub_date"], start_dt, end_dt)]
    if in_range:
        source = "Yahoo Finance search (quote feed empty)" if from_search else "Yahoo Finance"
        return (f"## {symbol} News, from {start_date} to {end_date} — source: {source}, "
                f"{len(in_range)} articles:\n\n{format_articles(in_range)}")

    if from_search:
        return (f"<Yahoo Finance news unavailable for {start_date}..{end_date}: Yahoo search returns "
                f"only a sample of recent articles about {symbol}, so this is not an absence of news>")
    gap = coverage_gap((a["pub_date"] for a in articles), start_date, end_date,
                       "Yahoo Finance news", f"news for {symbol}")
    return gap or f"No news found for {symbol} between {start_date} and {end_date}"


def get_news(ticker: str, start_date: str, end_date: str, limit: int = 25, company: str = "") -> str:
    symbol = ticker.upper()
    company = short_name(company) if company else resolve_company(symbol)
    return (from_google(symbol, company, start_date, end_date, limit)
            or from_yahoo(symbol, start_date, end_date, limit))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticker", required=True)
    p.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, help="YYYY-MM-DD (inclusive)")
    p.add_argument("--company", default="", help='company name to search with the ticker; looked up when omitted')
    p.add_argument("--limit", type=int, default=25)
    args = p.parse_args()
    try:
        print(get_news(args.ticker, args.start_date, args.end_date, args.limit, args.company))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
