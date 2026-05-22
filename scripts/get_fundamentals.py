#!/usr/bin/env python3
"""Retrieve company fundamentals overview (P/E, market cap, margins, etc.)."""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import yfinance as yf

from _common import die, now_iso, yf_retry

FIELDS = [
    ("Name", "longName"),
    ("Sector", "sector"),
    ("Industry", "industry"),
    ("Market Cap", "marketCap"),
    ("PE Ratio (TTM)", "trailingPE"),
    ("Forward PE", "forwardPE"),
    ("PEG Ratio", "pegRatio"),
    ("Price to Book", "priceToBook"),
    ("EPS (TTM)", "trailingEps"),
    ("Forward EPS", "forwardEps"),
    ("Dividend Yield", "dividendYield"),
    ("Beta", "beta"),
    ("52 Week High", "fiftyTwoWeekHigh"),
    ("52 Week Low", "fiftyTwoWeekLow"),
    ("50 Day Average", "fiftyDayAverage"),
    ("200 Day Average", "twoHundredDayAverage"),
    ("Revenue (TTM)", "totalRevenue"),
    ("Gross Profit", "grossProfits"),
    ("EBITDA", "ebitda"),
    ("Net Income", "netIncomeToCommon"),
    ("Profit Margin", "profitMargins"),
    ("Operating Margin", "operatingMargins"),
    ("Return on Equity", "returnOnEquity"),
    ("Return on Assets", "returnOnAssets"),
    ("Debt to Equity", "debtToEquity"),
    ("Current Ratio", "currentRatio"),
    ("Book Value", "bookValue"),
    ("Free Cash Flow", "freeCashflow"),
]


def get_fundamentals(ticker: str) -> str:
    obj = yf.Ticker(ticker.upper())
    info = yf_retry(lambda: obj.info)
    if not info:
        return f"No fundamentals data found for symbol '{ticker}'"

    lines = [f"{label}: {info.get(key)}" for label, key in FIELDS if info.get(key) is not None]
    header = (
        f"# Company Fundamentals for {ticker.upper()}\n"
        f"# Data retrieved on: {now_iso()}\n\n"
    )
    return header + "\n".join(lines)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ticker", required=True)
    p.add_argument("--curr-date", help="YYYY-MM-DD (informational only for yfinance)")
    args = p.parse_args()
    try:
        print(get_fundamentals(args.ticker))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
