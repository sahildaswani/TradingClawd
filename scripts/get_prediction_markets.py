#!/usr/bin/env python3
"""Prediction-market odds from Polymarket (keyless, ported from upstream TradingAgents).

  get_prediction_markets.py --topic "Fed rate" --curr-date 2026-10-14

Returns the most-traded open markets matching a topic, each with its implied
probability, traded volume, resolution date and one-week move. Polymarket serves
only live odds with no history, so a past-dated run gets nothing rather than odds
from after its date.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import die, is_historical

SEARCH_URL = "https://gamma-api.polymarket.com/public-search?{qs}"
UA = "tradingclawd/0.8 (+https://github.com/sahildaswani/TradingClawd)"


def _list(value) -> list:
    if isinstance(value, list):
        return value
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


def _open_and_future(market: dict, now: datetime) -> bool:
    if market.get("closed"):  # `active` stays true even after resolution; `closed` is reliable
        return False
    end = market.get("endDate")
    if not end:
        return True
    try:
        return datetime.fromisoformat(end.replace("Z", "+00:00")) > now
    except ValueError:
        return True


def prediction_markets(topic: str, as_of: str, limit: int = 8) -> str:
    if is_historical(as_of):
        return (f"<Prediction-market odds withheld for {as_of}: Polymarket serves only live odds, so they "
                f"would be from after the analysis date>")
    url = SEARCH_URL.format(qs=urlencode({"q": topic, "limit_per_type": 20}))
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=20) as resp:
            data = json.loads(resp.read())
    except (HTTPError, URLError, OSError, ValueError) as exc:
        return f"<Polymarket unavailable for '{topic}' ({exc}); proceed without prediction-market odds>"

    now = datetime.now(timezone.utc)
    markets = [m for event in data.get("events", []) for m in event.get("markets", []) if _open_and_future(m, now)]
    markets.sort(key=lambda m: m.get("volumeNum") or 0, reverse=True)
    header = (f'## Polymarket: "{topic}"\nLive market-implied probabilities; higher traded volume means a deeper, '
              f"more reliable price. A probability is the crowd's priced odds, not a certainty.\n\n")
    lines = []
    for m in markets:
        if len(lines) >= limit:
            break
        prices, outcomes = _list(m.get("outcomePrices")), _list(m.get("outcomes"))
        try:
            prob = float(prices[0])
        except (IndexError, TypeError, ValueError):
            continue
        if not 0.01 <= prob <= 0.99:
            continue  # a market priced at 0% or 100% says nothing the others don't
        week = m.get("oneWeekPriceChange")
        move = f", 1-week {week * 100:+.1f}pp" if isinstance(week, (int, float)) and week else ""
        lines.append(f"- **{m.get('question')}**: {outcomes[0] if outcomes else 'Yes'} {prob:.0%} "
                     f"(${(m.get('volumeNum') or 0):,.0f} traded, resolves {(m.get('endDate') or '')[:10]}{move})")
    if not lines:
        return header + (f"No open markets matched '{topic}'. Polymarket covers mostly macro, political, "
                         f"geopolitical and crypto events; a single stock often has none.")
    return header + "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--topic", required=True, help='e.g. "Fed rate", "recession", "tariffs", "bitcoin"')
    p.add_argument("--curr-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--limit", type=int, default=8)
    args = p.parse_args()
    try:
        print(prediction_markets(args.topic, args.curr_date, args.limit))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
