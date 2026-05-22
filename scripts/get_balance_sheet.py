#!/usr/bin/env python3
"""Retrieve balance sheet (quarterly or annual)."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import yfinance as yf

from _common import die, now_iso, yf_retry


def _filter_by_date(data: pd.DataFrame, curr_date: str | None) -> pd.DataFrame:
    if not curr_date or data.empty:
        return data
    cutoff = pd.Timestamp(curr_date)
    mask = pd.to_datetime(data.columns, errors="coerce") <= cutoff
    return data.loc[:, mask]


def get_balance_sheet(ticker: str, freq: str, curr_date: str | None) -> str:
    obj = yf.Ticker(ticker.upper())
    data = yf_retry(
        lambda: obj.quarterly_balance_sheet if freq.lower() == "quarterly" else obj.balance_sheet
    )
    data = _filter_by_date(data, curr_date)
    if data.empty:
        return f"No balance sheet data found for symbol '{ticker}'"

    header = (
        f"# Balance Sheet data for {ticker.upper()} ({freq})\n"
        f"# Data retrieved on: {now_iso()}\n\n"
    )
    return header + data.to_csv()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticker", required=True)
    p.add_argument("--freq", default="quarterly", choices=["quarterly", "annual"])
    p.add_argument("--curr-date", help="YYYY-MM-DD")
    args = p.parse_args()
    try:
        print(get_balance_sheet(args.ticker, args.freq, args.curr_date))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
