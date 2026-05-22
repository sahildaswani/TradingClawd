#!/usr/bin/env python3
"""Retrieve OHLCV stock price data for a ticker over a date range."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf

from _common import die, now_iso, parse_date, yf_retry


def get_stock_data(symbol: str, start_date: str, end_date: str) -> str:
    parse_date(start_date)
    parse_date(end_date)

    ticker = yf.Ticker(symbol.upper())
    data = yf_retry(lambda: ticker.history(start=start_date, end=end_date))

    if data.empty:
        return f"No data found for symbol '{symbol}' between {start_date} and {end_date}"

    if data.index.tz is not None:
        data.index = data.index.tz_localize(None)

    for col in ("Open", "High", "Low", "Close", "Adj Close"):
        if col in data.columns:
            data[col] = data[col].round(2)

    header = (
        f"# Stock data for {symbol.upper()} from {start_date} to {end_date}\n"
        f"# Total records: {len(data)}\n"
        f"# Data retrieved on: {now_iso()}\n\n"
    )
    return header + data.to_csv()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", required=True)
    p.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--end-date", required=True, help="YYYY-MM-DD")
    args = p.parse_args()
    try:
        print(get_stock_data(args.symbol, args.start_date, args.end_date))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
