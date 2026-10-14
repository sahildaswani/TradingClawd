#!/usr/bin/env python3
"""Retrieve OHLCV stock price data for a ticker over a date range (end date inclusive)."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import yfinance as yf

from _common import die, next_day, now_iso, parse_date, yf_retry

# A latest row more than this many days before the requested end date is stale data,
# not a quiet market: long holiday weekends stay well inside it.
MAX_STALE_DAYS = 10


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    parse_date(start_date)
    end_dt = parse_date(end_date)
    symbol = symbol.upper()

    data = yf_retry(lambda: yf.Ticker(symbol).history(start=start_date, end=next_day(end_date)))
    if data.empty:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    # Today on the exchange's own clock, to flag a session that is still open.
    exchange_today = pd.Timestamp.now(tz=data.index.tz).normalize().tz_localize(None)
    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)
    data = data[data.index.normalize() <= pd.Timestamp(end_dt)]
    if data.empty:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    latest = data.index[-1].normalize()
    stale_days = (pd.Timestamp(end_dt) - latest).days
    if stale_days > MAX_STALE_DAYS and end_dt <= pd.Timestamp.today():
        die(f"latest price row for {symbol} is {latest.date()}, {stale_days} days before "
            f"{end_date}; refusing stale data")

    for col in ("Open", "High", "Low", "Close", "Adj Close"):
        if col in data.columns:
            data[col] = data[col].round(2)

    header = (
        f"# Stock data for {symbol} from {start_date} to {end_date}\n"
        f"# Total records: {len(data)}\n"
        f"# Data retrieved on: {now_iso()}\n"
    )
    if latest == exchange_today:
        header += f"# The {latest.date()} row is today's: final only if the session has closed\n"
    header += "\n"
    return header + data.to_csv()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", required=True)
    p.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, help="YYYY-MM-DD (inclusive)")
    args = p.parse_args()
    try:
        print(get_stock_data(args.symbol, args.start_date, args.end_date))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
