"""Google News RSS search: dated headlines for a query within a date window.

Keyless. Google's search operators ``after:`` and ``before:`` bound the window, so
past-dated runs get the news of their own week rather than today's. Each item has
a title, publisher, publish time and link; there is no article text. Google caps a
search at 100 items, ranked by relevance.
"""

import xml.etree.ElementTree as ET
from datetime import timedelta
from email.utils import parsedate_to_datetime
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from _common import in_window, parse_date

URL = "https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"
UA = "tradingclawd/0.5 (+https://github.com/sahildaswani/TradingClawd)"
MAX_BYTES = 5 * 1024 * 1024


class GoogleNewsError(Exception):
    pass


def search(query: str, start_date: str, end_date: str) -> list[dict]:
    """Articles matching ``query`` published in [start_date, end_date] (UTC, end inclusive).

    Items come back in Google's relevance order, shaped like ``_common.extract_article``.
    Raises GoogleNewsError when the feed cannot be fetched or read.
    """
    start_dt, end_dt = parse_date(start_date), parse_date(end_date)
    # Google applies after:/before: in its own time zone; ask a day wider on each
    # side and trim to the exact UTC window below.
    after = (start_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    before = (end_dt + timedelta(days=2)).strftime("%Y-%m-%d")
    url = URL.format(q=quote(f"{query} after:{after} before:{before}"))
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=20) as resp:
            body = resp.read(MAX_BYTES + 1)
    except HTTPError as exc:
        raise GoogleNewsError(f"HTTP {exc.code}") from exc
    except OSError as exc:
        raise GoogleNewsError(str(exc)) from exc
    if len(body) > MAX_BYTES:
        raise GoogleNewsError("feed exceeded size limit")
    try:
        items = ET.fromstring(body).findall("./channel/item")
    except ET.ParseError as exc:
        raise GoogleNewsError(f"unreadable feed ({exc})") from exc

    articles = []
    for item in items:
        publisher = (item.findtext("source") or "").strip() or "Unknown"
        title = (item.findtext("title") or "").strip()
        # Google appends " - Publisher" to every title.
        suffix = f" - {publisher}"
        if title.endswith(suffix):
            title = title[: -len(suffix)]
        try:
            pub_date = parsedate_to_datetime(item.findtext("pubDate") or "")
        except (TypeError, ValueError):
            pub_date = None
        if pub_date is None or not in_window(pub_date, start_dt, end_dt):
            continue
        articles.append({
            "title": title or "No title",
            "summary": "",
            "publisher": publisher,
            "link": (item.findtext("link") or "").strip(),
            "pub_date": pub_date,
        })
    return articles
