#!/usr/bin/env python3
"""Retrieve recent insider transaction filings for a ticker."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf

from _common import die, now_iso, yf_retry


def get_insider_transactions(ticker: str) -> str:
    obj = yf.Ticker(ticker.upper())
    data = yf_retry(lambda: obj.insider_transactions)
    if data is None or data.empty:
        return f"No insider transactions data found for symbol '{ticker}'"

    header = (
        f"# Insider Transactions data for {ticker.upper()}\n"
        f"# Data retrieved on: {now_iso()}\n\n"
    )
    return header + data.to_csv()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticker", required=True)
    args = p.parse_args()
    try:
        print(get_insider_transactions(args.ticker))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
