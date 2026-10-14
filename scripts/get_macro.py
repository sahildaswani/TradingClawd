#!/usr/bin/env python3
"""Macro indicators from FRED (St. Louis Fed), keyless, to ground macro commentary in data.

  get_macro.py --curr-date 2026-10-14 [--indicators cpi,core_pce,fed_funds_rate,...]

Reads FRED's public CSV download, which needs no API key and serves each series'
latest revision. A past-dated run therefore cannot see a series as it was first
published; to keep it from reading data released after its date, an observation
counts only once a conservative publication lag has passed (about 6 weeks for a
monthly series, 13 for a quarterly one, a week for a weekly one, a day for a daily
one). Live runs see everything published so far.
"""

import argparse
import csv
import io
import os
import sys
from datetime import date, datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import die, is_historical, parse_date

CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}&coed={end}"
UA = "tradingclawd/0.8 (+https://github.com/sahildaswani/TradingClawd)"

# name: (FRED series, description, frequency, unit)
SERIES = {
    "fed_funds_rate": ("FEDFUNDS", "Effective federal funds rate", "monthly", "%"),
    "2y_treasury": ("DGS2", "2-year Treasury yield", "daily", "%"),
    "10y_treasury": ("DGS10", "10-year Treasury yield", "daily", "%"),
    "yield_curve": ("T10Y2Y", "10y minus 2y Treasury spread", "daily", "pp"),
    "cpi": ("CPIAUCSL", "CPI, all items (index)", "monthly", "index"),
    "core_cpi": ("CPILFESL", "Core CPI, ex food and energy (index)", "monthly", "index"),
    "core_pce": ("PCEPILFE", "Core PCE price index", "monthly", "index"),
    "inflation_expectations": ("T10YIE", "10-year breakeven inflation", "daily", "%"),
    "unemployment": ("UNRATE", "Unemployment rate", "monthly", "%"),
    "payrolls": ("PAYEMS", "Nonfarm payrolls (thousands)", "monthly", "k"),
    "initial_claims": ("ICSA", "Initial jobless claims", "weekly", "count"),
    "real_gdp": ("GDPC1", "Real GDP (billions, chained 2017 $)", "quarterly", "bn"),
    "industrial_production": ("INDPRO", "Industrial production index", "monthly", "index"),
    "retail_sales": ("RSAFS", "Retail sales (millions $)", "monthly", "mn"),
    "consumer_sentiment": ("UMCSENT", "U. Michigan consumer sentiment", "monthly", "index"),
    "vix": ("VIXCLS", "VIX volatility index", "daily", "index"),
    "dollar_index": ("DTWEXBGS", "Broad trade-weighted dollar index", "daily", "index"),
    "ecb_deposit_rate": ("ECBDFR", "ECB deposit facility rate", "daily", "%"),
    "euro_hicp": ("CP0000EZ19M086NEST", "Euro area HICP (index)", "monthly", "index"),
}
DEFAULT = ["fed_funds_rate", "2y_treasury", "10y_treasury", "yield_curve", "core_cpi", "core_pce",
           "unemployment", "payrolls", "initial_claims", "inflation_expectations", "vix"]
LAG = {"daily": 1, "weekly": 7, "monthly": 45, "quarterly": 90}
LOOK_BACK = {"daily": 120, "weekly": 120, "monthly": 500, "quarterly": 900}
SHOW = {"daily": 6, "weekly": 6, "monthly": 6, "quarterly": 5}
INDEX_UNITS = {"index"}


def fetch(series_id: str, start: str, end: str) -> list[tuple[str, float]]:
    url = CSV_URL.format(series=series_id, start=start, end=end)
    try:
        with urlopen(Request(url, headers={"User-Agent": UA}), timeout=20) as resp:
            text = resp.read().decode("utf-8")
    except (HTTPError, URLError, OSError) as exc:
        raise RuntimeError(f"FRED unavailable ({exc})") from exc
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) != 2 or row[0] in ("DATE", "observation_date"):
            continue
        try:
            rows.append((row[0], float(row[1])))
        except ValueError:
            continue  # "." marks a missing observation
    return rows


def describe(name: str, as_of: str) -> str:
    series_id, label, freq, unit = SERIES[name]
    as_of_dt = parse_date(as_of)
    start = (as_of_dt - timedelta(days=LOOK_BACK[freq])).strftime("%Y-%m-%d")
    try:
        rows = fetch(series_id, start, as_of)
    except RuntimeError as exc:
        return f"- **{label}** ({series_id}): <unavailable: {exc}>"
    if is_historical(as_of):
        cutoff = (as_of_dt - timedelta(days=LAG[freq])).strftime("%Y-%m-%d")
        rows = [r for r in rows if r[0] <= cutoff]
    if not rows:
        return f"- **{label}** ({series_id}): <no observations known by {as_of}>"
    shown = rows[-SHOW[freq]:]
    latest_date, latest = shown[-1]
    line = f"- **{label}** ({series_id}, {freq}): {latest:,.2f}{'' if unit in INDEX_UNITS | {'k', 'bn', 'mn', 'count'} else unit} as of {latest_date}"
    if unit in INDEX_UNITS and freq == "monthly" and len(rows) >= 13:
        prior = dict(rows).get(_year_ago(latest_date))
        if prior:
            line += f"; {latest / prior - 1:+.1%} year over year"
    if len(shown) > 1:
        prev_date, prev = shown[-2]
        line += f"; previous {prev:,.2f} ({prev_date})"
    line += "\n  recent: " + ", ".join(f"{d} {v:,.2f}" for d, v in shown)
    return line


def _year_ago(d: str) -> str:
    dt = parse_date(d)
    return f"{dt.year - 1:04d}-{dt.month:02d}-{dt.day:02d}"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--curr-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--indicators", default=",".join(DEFAULT),
                   help=f"comma-separated, from: {', '.join(SERIES)}")
    args = p.parse_args()
    names = [n.strip() for n in args.indicators.split(",") if n.strip()]
    unknown = [n for n in names if n not in SERIES]
    if unknown:
        die(f"unknown indicator(s) {', '.join(unknown)}; choose from {', '.join(SERIES)}")
    try:
        header = (f"## Macro indicators from FRED, as known on {args.curr_date}\n"
                  + ("Past-dated run: observations count only after a conservative publication lag, and values "
                     "are the latest revision, which may differ from what was first published.\n"
                     if is_historical(args.curr_date) else "Latest published values.\n"))
        print(header + "\n".join(describe(n, args.curr_date) for n in names))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
