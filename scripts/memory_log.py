#!/usr/bin/env python3
"""Maintain the TradingClawd decision log (${data_dir}/memory/trading_memory.md).

  memory_log.py append --data-dir D --ticker T --trade-date YYYY-MM-DD --results-dir R

``append`` records the decision in R/portfolio_decision.json as a pending entry.
It is idempotent: a ticker already logged for that date is not logged again, so a
re-run never counts the same decision twice.
"""

import argparse
import fcntl
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import die

HEADER = "# TradingClawd decision log\n\n"


def append(data_dir: str, ticker: str, trade_date: str, results_dir: str) -> str:
    decision_path = os.path.join(results_dir, "portfolio_decision.json")
    try:
        with open(decision_path) as f:
            decision = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        die(f"cannot read {decision_path}: {exc}")
    rating = decision.get("rating")
    summary = (decision.get("executive_summary") or "").strip()
    if rating not in ("Buy", "Overweight", "Hold", "Underweight", "Sell"):
        rating = "REVIEW"

    log_path = os.path.join(data_dir, "memory", "trading_memory.md")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    tag = f"## {trade_date} | {ticker.upper()} | "
    with open(log_path, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)  # several tickers' managers may finish at once
        f.seek(0)
        existing = f.read()
        if any(line.startswith(tag) for line in existing.splitlines()):
            return f"already logged: {ticker.upper()} {trade_date}"
        if not existing:
            f.write(HEADER)
        f.write(f"{tag}{rating} | pending\n{summary}\n\n")
    return f"logged: {ticker.upper()} {trade_date} {rating}"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    a = sub.add_parser("append", help="log the decision in a results directory")
    a.add_argument("--data-dir", required=True)
    a.add_argument("--ticker", required=True)
    a.add_argument("--trade-date", required=True)
    a.add_argument("--results-dir", required=True)
    args = p.parse_args()
    print(append(args.data_dir, args.ticker, args.trade_date, args.results_dir))


if __name__ == "__main__":
    main()
