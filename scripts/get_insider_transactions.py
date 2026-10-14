#!/usr/bin/env python3
"""Retrieve recent insider transaction filings for a ticker."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import yfinance as yf

from _common import die, is_historical, now_iso, parse_date, yf_retry


# A trade becomes public when its Form 4 is filed, up to two business days later:
# four calendar days covers a weekend in between.
DISCLOSURE_LAG_DAYS = 4


def get_insider_transactions(ticker: str, curr_date: str | None = None) -> str:
    obj = yf.Ticker(ticker.upper())
    data = yf_retry(lambda: obj.insider_transactions)
    if data is None or data.empty:
        return f"No insider transactions data found for symbol '{ticker}'"

    note = ""
    if is_historical(curr_date) and "Start Date" in data.columns:
        cutoff = pd.Timestamp(parse_date(curr_date)) - pd.Timedelta(days=DISCLOSURE_LAG_DAYS)
        data = data[pd.to_datetime(data["Start Date"], errors="coerce") <= cutoff]
        note = (f"# Past-dated run: only trades dated on or before {cutoff.date()}, which were public by "
                f"{curr_date} (Form 4 is filed up to two business days after a trade)\n")
        if data.empty:
            return f"No insider transactions for {ticker.upper()} known by {curr_date}"

    header = (
        f"# Insider Transactions data for {ticker.upper()}\n"
        f"# Data retrieved on: {now_iso()}\n{note}\n"
    )
    return header + data.to_csv()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticker", required=True)
    p.add_argument("--curr-date", help="YYYY-MM-DD; a past date keeps only trades public by then")
    args = p.parse_args()
    try:
        print(get_insider_transactions(args.ticker, args.curr_date))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
