#!/usr/bin/env python3
"""Prepare a TradingClawd run and print it as JSON: the arguments for the
tradingclawd:trade-pipeline workflow.

Resolves paths and the trade date, validates tickers, creates each ticker's
results directory, checks that the stages being skipped left their outputs on
disk, and moves outputs of the stages about to run, and of every later stage
that builds on them, into _previous_runs/ so a re-run never mixes old and new files. Exits non-zero with a message on stderr
when the run cannot start.
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date, datetime

STAGES = ("analyze", "debate", "decide")
TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-^=+]{0,31}$")
ANALYST_REPORTS = ("market_report.md", "sentiment_report.md", "news_report.md", "fundamentals_report.md")
# What each stage writes, relative to a ticker's results directory.
STAGE_OUTPUTS = {
    "analyze": ANALYST_REPORTS,
    "debate": ("debate_turns", "research_plan.json"),
    "decide": ("trader_proposal.json", "risk_turns", "portfolio_decision.json"),
}
SKILL_FOR_STAGE = {"analyze": "/tradingclawd:trade-analyze", "debate": "/tradingclawd:trade-debate"}


def fail(msg: str) -> None:
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(1)


def parse_tickers(raw: str) -> list[str]:
    tickers = []
    for piece in re.split(r"[,\s]+", raw.strip()):
        t = piece.strip().upper()
        if not t:
            continue
        if not TICKER_RE.match(t):
            fail(f"'{piece}' is not a ticker symbol")
        if t not in tickers:
            tickers.append(t)
    if not tickers:
        fail("no tickers given")
    return tickers


def parse_trade_date(raw: str | None) -> str:
    today = date.today()
    if not raw:
        return today.strftime("%Y-%m-%d")
    try:
        d = datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        fail(f"trade date '{raw}' is not YYYY-MM-DD")
    if d > today:
        fail(f"trade date {raw} is in the future")
    return d.strftime("%Y-%m-%d")


def missing_prerequisites(results_dir: str, start_at: str) -> list[str]:
    needed = []
    if STAGES.index(start_at) > 0:
        needed += ANALYST_REPORTS
    if STAGES.index(start_at) > 1:
        needed.append("research_plan.json")
    return [f for f in needed
            if not os.path.isfile(os.path.join(results_dir, f))
            or os.path.getsize(os.path.join(results_dir, f)) == 0]


def set_aside_outputs(results_dir: str, stages: list[str], stamp: str) -> list[str]:
    """Move the outputs of the stages about to run into _previous_runs/<stamp>/."""
    moved = []
    for stage in stages:
        for name in STAGE_OUTPUTS[stage]:
            src = os.path.join(results_dir, name)
            if not os.path.exists(src) or (os.path.isdir(src) and not os.listdir(src)):
                continue
            dest_dir = os.path.join(results_dir, "_previous_runs", stamp)
            os.makedirs(dest_dir, exist_ok=True)
            shutil.move(src, os.path.join(dest_dir, name))
            moved.append(name)
    return moved


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tickers", required=True, help="comma-separated, e.g. NVDA,AAPL")
    p.add_argument("--date", help="trade date YYYY-MM-DD (default: today)")
    p.add_argument("--data-dir", help="default: $TRADINGCLAWD_DIR, else ./.tradingclawd")
    p.add_argument("--debate-rounds", type=int, default=1)
    p.add_argument("--risk-rounds", type=int, default=1)
    p.add_argument("--start-at", choices=STAGES, default="analyze")
    p.add_argument("--stop-after", choices=STAGES, default="decide")
    args = p.parse_args()

    if STAGES.index(args.start_at) > STAGES.index(args.stop_after):
        fail(f"--start-at {args.start_at} comes after --stop-after {args.stop_after}")
    for name in ("debate_rounds", "risk_rounds"):
        if not 1 <= getattr(args, name) <= 5:
            fail(f"--{name.replace('_', '-')} must be between 1 and 5")

    plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.abspath(os.path.expanduser(
        args.data_dir or os.environ.get("TRADINGCLAWD_DIR") or os.path.join(os.getcwd(), ".tradingclawd")
    ))
    if os.path.commonpath([data_dir, plugin_dir]) == plugin_dir:
        fail(f"data dir {data_dir} is inside the plugin directory; results must live outside it")
    trade_date = parse_trade_date(args.date)
    tickers = parse_tickers(args.tickers)
    stages = list(STAGES[STAGES.index(args.start_at): STAGES.index(args.stop_after) + 1])
    # Later stages build on this one, so their old outputs go stale too.
    stale = list(STAGES[STAGES.index(args.start_at):])

    # Check every ticker before touching any of them.
    entries, problems = [], []
    for t in tickers:
        results_dir = os.path.join(data_dir, "results", t, trade_date)
        missing = missing_prerequisites(results_dir, args.start_at)
        if missing:
            earlier = STAGES[STAGES.index(args.start_at) - 1]
            problems.append(f"{t}: missing {', '.join(missing)} in {results_dir} "
                            f"(run {SKILL_FOR_STAGE[earlier]} {t} {trade_date} first)")
        entries.append({"ticker": t, "results_dir": results_dir})
    if problems:
        fail("cannot start at '" + args.start_at + "':\n  " + "\n  ".join(problems))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for e in entries:
        os.makedirs(e["results_dir"], exist_ok=True)
        e["set_aside"] = set_aside_outputs(e["results_dir"], stale, stamp)
        for sub in ("debate_turns", "risk_turns"):
            os.makedirs(os.path.join(e["results_dir"], sub), exist_ok=True)

    per_ticker = ((4 if "analyze" in stages else 0)
                  + (2 * args.debate_rounds + 1 if "debate" in stages else 0)
                  + (1 + 3 * args.risk_rounds + 1 if "decide" in stages else 0))
    print(json.dumps({
        "plugin_dir": plugin_dir,
        "data_dir": data_dir,
        "memory_log": os.path.join(data_dir, "memory", "trading_memory.md"),
        "trade_date": trade_date,
        "debate_rounds": args.debate_rounds,
        "risk_rounds": args.risk_rounds,
        "start_at": args.start_at,
        "stop_after": args.stop_after,
        "agents_planned": per_ticker * len(entries),
        "tickers": entries,
    }, indent=2))


if __name__ == "__main__":
    main()
