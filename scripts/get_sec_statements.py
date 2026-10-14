#!/usr/bin/env python3
"""Financial statements as they were filed with the SEC, for US filers (ported from
upstream TradingAgents).

Yahoo serves a period's current value, cut at the fiscal period end. That is two
claims a past-dated run should not make: a period is not public until the company
files, weeks after it ends, and a figure restated later is not what investors saw.
EDGAR dates every fact by its filing, so a run dated D sees exactly what was on
file by D, restatements included only from the day they were filed.

No key; SEC requires a User-Agent with a contact address (set SEC_EDGAR_USER_AGENT
to your own "Name email"). Filings are cached for a day under ~/.cache/tradingclawd.
"""

import argparse
import json
import os
import sys
import time
from datetime import date, datetime
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import die

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
CACHE_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"), "tradingclawd", "sec_edgar")
CACHE_TTL = 24 * 60 * 60

# Line items and the tags filers use for each, best first. First match wins and
# values are never summed across tags, which would double count.
STATEMENTS = {
    "balance": ("Balance Sheet", [
        ("Total Assets", ("Assets",)),
        ("Current Assets", ("AssetsCurrent",)),
        ("Cash and Equivalents", ("CashAndCashEquivalentsAtCarryingValue",)),
        ("Total Liabilities", ("Liabilities",)),
        ("Current Liabilities", ("LiabilitiesCurrent",)),
        ("Long-Term Debt", ("LongTermDebtNoncurrent", "LongTermDebt")),
        ("Stockholders Equity", ("StockholdersEquity",
                                 "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest")),
    ]),
    "income": ("Income Statement", [
        ("Revenue", ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")),
        ("Cost of Revenue", ("CostOfRevenue", "CostOfGoodsAndServicesSold")),
        ("Gross Profit", ("GrossProfit",)),
        ("Operating Income", ("OperatingIncomeLoss",)),
        ("Net Income", ("NetIncomeLoss",)),
        ("Diluted EPS", ("EarningsPerShareDiluted",)),
    ]),
    "cashflow": ("Cash Flow Statement", [
        ("Operating Cash Flow", ("NetCashProvidedByUsedInOperatingActivities",
                                 "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")),
        ("Investing Cash Flow", ("NetCashProvidedByUsedInInvestingActivities",)),
        ("Financing Cash Flow", ("NetCashProvidedByUsedInFinancingActivities",)),
        ("Capital Expenditure", ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")),
        ("Share Repurchases", ("PaymentsForRepurchaseOfCommonStock",)),
    ]),
}
# A quarter spans about 90 days and a year about 365; one filing reports the quarter
# and the year to date under the same end date. 10-Q cash flows are often filed only
# year to date: those are shown with their span, never differenced into a quarter.
SPANS = {"quarterly": (60, 115), "annual": (300, 400)}
YEAR_TO_DATE = ((150, 200, 6), (240, 290, 9))
ANNUAL_FORMS = ("10-K", "20-F", "40-F")


def user_agent() -> str:
    return os.environ.get("SEC_EDGAR_USER_AGENT", "").strip() or "TradingClawd/0.8 (contact@example.com)"


def fetch_json(url: str, cache_name: str) -> dict:
    path = os.path.join(CACHE_DIR, cache_name)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < CACHE_TTL:
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except ValueError:
            pass
    try:
        with urlopen(Request(url, headers={"User-Agent": user_agent()}), timeout=30) as resp:
            data = json.loads(resp.read())
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise RuntimeError(f"SEC EDGAR unavailable ({exc})") from exc
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)
    return data


def cik_for(ticker: str) -> str | None:
    wanted = ticker.strip().upper().replace("-", ".")  # Yahoo BRK-B is SEC BRK.B
    for entry in fetch_json(TICKERS_URL, "company_tickers.json").values():
        if entry.get("ticker", "").upper() in (wanted, ticker.strip().upper()):
            return f"{int(entry['cik_str']):010d}"
    return None


def span_index(fact: dict, spans) -> int | None:
    if "start" not in fact:
        return 0  # a balance is an instant and fits any span
    days = (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days
    return next((i for i, (low, high) in enumerate(spans) if low <= days <= high), None)


def known_by(facts: dict, tags, as_of: str, spans, forms=()) -> tuple[dict, str]:
    """{(period end, span index): value} as filed on or before ``as_of``, and the unit."""
    values, chosen_unit = {}, "USD"
    for tag in tags:
        for unit, unit_values in ((facts.get(tag) or {}).get("units", {})).items():
            latest, covered = {}, set()
            for fact in unit_values:
                index = span_index(fact, spans)
                key = (fact["end"], index)
                if fact["filed"] > as_of or index is None or key in values:
                    continue
                if not forms or fact.get("form", "").startswith(forms):
                    covered.add(key)
                if key not in latest or fact["filed"] >= latest[key]["filed"]:
                    latest[key] = fact  # an amendment counts from the day it was filed
            latest = {k: f for k, f in latest.items() if k in covered}
            if latest:
                chosen_unit = unit
                values.update({k: f["val"] for k, f in latest.items()})
    return dict(sorted(values.items())), chosen_unit


def statement(kind: str, ticker: str, freq: str, as_of: str, periods_shown: int = 6) -> str:
    title, line_items = STATEMENTS[kind]
    cik = cik_for(ticker)
    if cik is None:
        return f"<SEC EDGAR has no filings for {ticker.upper()}: not a US SEC filer; use the Yahoo statement instead>"
    us_gaap = (fetch_json(FACTS_URL.format(cik=cik), f"CIK{cik}.json").get("facts") or {}).get("us-gaap")
    if not us_gaap:
        return f"<SEC EDGAR has no us-gaap facts for {ticker.upper()}>"

    quarterly = freq == "quarterly"
    if quarterly:
        spans = (SPANS["quarterly"], *((lo, hi) for lo, hi, _ in YEAR_TO_DATE))
        names = ["", *(f" ({m} months)" for _, _, m in YEAR_TO_DATE)]
    else:
        spans, names = (SPANS["annual"],), [""]
    lines = {label: known_by(us_gaap, tags, as_of, spans, () if quarterly else ANNUAL_FORMS)
             for label, tags in line_items}
    chosen = {label: {} for label in lines}
    for label, (values, _) in lines.items():
        for end, index in values:
            chosen[label][end] = min(index, chosen[label].get(end, index))
    periods = sorted({(end, i) for spans_of in chosen.values() for end, i in spans_of.items()})[-periods_shown:]
    if not periods:
        return f"<SEC EDGAR: no {freq} {title.lower()} for {ticker.upper()} filed by {as_of}>"

    rows = [",".join([""] + [end + names[i] for end, i in periods])]
    for label, (values, unit) in lines.items():
        if not values:
            rows.append(",".join([label] + ["not tagged by this filer"] * len(periods)))
            continue
        cells = []
        for end, i in periods:
            v = values.get((end, i)) if chosen[label].get(end) == i else None
            cells.append("" if v is None else f"{v / 1e6:.0f}" if unit == "USD" else f"{v:.2f}")
        rows.append(",".join([label if unit == "USD" else f"{label} ({unit})"] + cells))
    return (f"# {title} for {ticker.upper()} ({freq}), USD millions unless the row says otherwise\n"
            f"# SEC EDGAR, as filed on or before {as_of} (restatements count only from their filing date)\n\n"
            + "\n".join(rows) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ticker", required=True)
    p.add_argument("--statement", required=True, choices=sorted(STATEMENTS))
    p.add_argument("--freq", default="quarterly", choices=["quarterly", "annual"])
    p.add_argument("--curr-date", default=datetime.now().strftime("%Y-%m-%d"), help="YYYY-MM-DD")
    args = p.parse_args()
    try:
        print(statement(args.statement, args.ticker, args.freq, args.curr_date))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
