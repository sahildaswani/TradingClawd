#!/usr/bin/env python3
"""Verified market-data snapshot: the source of truth for exact price and indicator claims.

Deterministic, no model involved (ported from upstream TradingAgents). Prints the
latest OHLCV row on or before the analysis date exactly as the vendor reported it
(never gap-filled), a fixed set of indicators on that row, and the recent closes.
The market analyst quotes exact numbers from here; if another tool disagrees, it
flags the discrepancy instead of reconciling it.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import yfinance as yf
from stockstats import wrap

from _common import die, next_day, parse_date, yf_retry

INDICATORS = ("close_10_ema", "close_50_sma", "close_200_sma", "rsi", "boll", "boll_ub", "boll_lb",
              "macd", "macds", "macdh", "atr")


def _fmt(value) -> str:
    if value is None or pd.isna(value):
        return "N/A"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return f"{value:,}" if isinstance(value, int) else str(value)


def snapshot(symbol: str, as_of: str, recent: int = 20) -> str:
    symbol = symbol.upper()
    start = (pd.Timestamp(parse_date(as_of)) - pd.DateOffset(years=2)).strftime("%Y-%m-%d")
    hist = yf_retry(lambda: yf.Ticker(symbol).history(start=start, end=next_day(as_of), auto_adjust=True))
    if hist is None or hist.empty:
        return f"<Market snapshot unavailable for {symbol}: no price rows up to {as_of}>"
    exchange_today = pd.Timestamp.now(tz=hist.index.tz).strftime("%Y-%m-%d")
    if hist.index.tz is not None:
        hist.index = hist.index.tz_localize(None)
    df = hist.reset_index()
    df["Date"] = pd.to_datetime(df["Date"]).dt.normalize()
    df = df[df["Date"] <= pd.Timestamp(as_of)].dropna(subset=["Close"])  # as reported, no gap filling
    if df.empty:
        return f"<Market snapshot unavailable for {symbol}: no price rows on or before {as_of}>"

    stock = wrap(df[["Date", "Open", "High", "Low", "Close", "Volume"]].copy())
    values = {}
    for name in INDICATORS:
        try:
            values[name] = _fmt(float(stock[name].iloc[-1]))
        except Exception as exc:  # one bad indicator must not sink the snapshot
            values[name] = f"N/A ({type(exc).__name__})"

    latest = df.iloc[-1]
    latest_date = latest["Date"].strftime("%Y-%m-%d")
    partial = latest_date == exchange_today
    lines = [
        f"## Verified market data snapshot for {symbol}",
        "",
        f"- Requested analysis date: {as_of}",
        f"- Latest trading row used: {latest_date}"
        + (" (today's session: final only if the session has closed)" if partial else ""),
        "- Rows after the analysis date are excluded; prices are as the vendor reported them, never gap-filled.",
        "",
        "### Latest OHLCV row",
        "",
        "| Field | Value |",
        "|---|---:|",
    ]
    for field in ("Open", "High", "Low", "Close", "Volume"):
        v = latest[field]
        lines.append(f"| {field} | {_fmt(int(v) if field == 'Volume' else float(v))} |")
    lines += ["", "### Indicators on the latest row", "", "| Indicator | Value |", "|---|---:|"]
    lines += [f"| {k} | {v} |" for k, v in values.items()]
    tail = df.tail(recent)
    lines += ["", f"### Recent closes (last {len(tail)} rows)", "", "| Date | Close |", "|---|---:|"]
    lines += [f"| {r.Date:%Y-%m-%d} | {_fmt(float(r.Close))} |" for r in tail.itertuples()]
    lines += [
        "",
        "Treat this snapshot as the source of truth for exact OHLCV, price-level and indicator-value claims. "
        "If another tool's output conflicts with it, flag the discrepancy rather than inventing a reconciled "
        "number. Do not claim historical validation, support/resistance bounces or exact percentage moves "
        "unless tool output with concrete dates and prices supports them.",
    ]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", required=True)
    p.add_argument("--curr-date", required=True, help="YYYY-MM-DD")
    args = p.parse_args()
    try:
        print(snapshot(args.symbol, args.curr_date))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
