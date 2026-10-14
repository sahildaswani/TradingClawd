#!/usr/bin/env python3
"""Prepare a TradingClawd run and print it as JSON: the arguments for the
tradingclawd:trade-pipeline workflow.

Resolves paths and the trade date, validates tickers, creates each ticker's
results directory, checks that the stages being skipped left their outputs on
disk, and moves outputs of the stages about to run, and of every later stage
that builds on them, into _previous_runs/ so a re-run never mixes old and new files.
For a run that ends in a decision, it also scores past decisions whose holding
window has traded (see memory_log.py settle-due). Exits non-zero with a message on stderr
when the run cannot start.
"""

import argparse
import json
import os
import re
import shutil
import sys
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from identity import instrument_context, resolve
from symbols import asset_type, normalize_symbol

STAGES = ("analyze", "debate", "decide")
TICKER_RE = re.compile(r"^[A-Z0-9^][A-Z0-9.\-^=+]{0,31}$")
ANALYST_REPORTS = ("market_report.md", "sentiment_report.md", "news_report.md", "fundamentals_report.md")
ANALYSTS = {"market": "market_report.md", "social": "sentiment_report.md", "news": "news_report.md",
            "fundamentals": "fundamentals_report.md"}
NO_PORTFOLIO = ("Portfolio context: not provided. You do not know the caller's current holdings or cash, so do "
                "not assume a flat book; give direction and sizing guidance in terms the caller can apply to "
                "their own position.")
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


def parse_tickers(raw: str) -> list[tuple[str, str]]:
    """(Yahoo symbol, symbol as the user wrote it) per ticker, de-duplicated by Yahoo symbol."""
    tickers = []
    for piece in re.split(r"[,\s]+", raw.strip()):
        t = piece.strip().upper()
        if not t:
            continue
        if not TICKER_RE.match(t):
            fail(f"'{piece}' is not a ticker symbol")
        canonical = normalize_symbol(t)
        if canonical not in (c for c, _ in tickers):
            tickers.append((canonical, t))
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


def parse_analysts(raw: str | None) -> list[str]:
    if not raw:
        return list(ANALYSTS)
    chosen = [a.strip().lower() for a in raw.split(",") if a.strip()]
    chosen = ["social" if a == "sentiment" else a for a in chosen]
    unknown = [a for a in chosen if a not in ANALYSTS]
    if unknown or not chosen:
        fail(f"unknown analyst(s) {', '.join(unknown) or '(none)'}; choose from {', '.join(ANALYSTS)}")
    return [a for a in ANALYSTS if a in chosen]


def load_portfolio(path: str | None, data_dir: str) -> tuple[dict | None, str | None]:
    """The caller's book from --portfolio, else <data_dir>/portfolio.json if present."""
    path = path or os.path.join(data_dir, "portfolio.json")
    if not os.path.exists(path):
        return None, None
    try:
        with open(os.path.expanduser(path), encoding="utf-8") as f:
            book = json.load(f)
        for pos in book.get("positions", []):
            pos["ticker"] = normalize_symbol(str(pos["ticker"]))
            float(pos["quantity"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        fail(f"portfolio file {path} is not usable ({exc}); expected "
             '{"cash": 25000, "currency": "USD", "positions": [{"ticker": "NVDA", "quantity": 100, "average_price": 180.5}]}')
    return book, os.path.abspath(path)


def render_portfolio(book: dict | None, ticker: str) -> str:
    if book is None:
        return NO_PORTFOLIO
    positions = book.get("positions", [])
    held = next((p for p in positions if p["ticker"] == ticker), None)
    lines = []
    if held is None:
        lines.append(f"- No current position in {ticker}")
    else:
        avg = held.get("average_price")
        lines.append(f"- Current position in {ticker}: {float(held['quantity']):,.4g} units"
                     + (f", average price {float(avg):,.2f}" if avg is not None else "")
                     + (" (short)" if float(held["quantity"]) < 0 else ""))
    if book.get("cash") is not None:
        lines.append(f"- Cash available: {float(book['cash']):,.2f}" + (f" {book['currency']}" if book.get("currency") else ""))
    others = [p for p in positions if p is not held]
    if others:
        lines.append("- Other positions: " + ", ".join(f"{p['ticker']} {float(p['quantity']):,.4g}" for p in others))
    return "Portfolio at the analysis date (from the caller's portfolio file):\n" + "\n".join(lines)


def parse_dates(args) -> list[str]:
    """One trade date (--date, default today), a list (--dates), or a range (--date-range START:END:STEP_DAYS)."""
    if args.dates:
        dates = [parse_trade_date(d.strip()) for d in args.dates.split(",") if d.strip()]
    elif args.date_range:
        try:
            start, end, step = args.date_range.split(":")
            cur, last, step = datetime.strptime(start, "%Y-%m-%d"), datetime.strptime(end, "%Y-%m-%d"), int(step)
        except ValueError:
            fail(f"--date-range {args.date_range!r} must be START:END:STEP_DAYS, e.g. 2026-07-01:2026-09-30:14")
        if step < 1 or cur > last:
            fail("--date-range needs START on or before END and a step of at least 1 day")
        dates = []
        while cur <= last:
            dates.append(parse_trade_date(cur.strftime("%Y-%m-%d")))
            cur += timedelta(days=step)
    else:
        dates = [parse_trade_date(args.date)]
    return sorted(set(dates))


def missing_prerequisites(results_dir: str, start_at: str, kind: str) -> list[str]:
    needed = []
    if STAGES.index(start_at) > 0:
        # Only a company has fundamentals; other instruments never get that report.
        # The debate works with whichever reports exist, so only the market report
        # (the price levels the trader needs) and at least one other are required.
        present = [r for r in ANALYST_REPORTS
                   if os.path.isfile(os.path.join(results_dir, r)) and os.path.getsize(os.path.join(results_dir, r))]
        if not present:
            needed += [r for r in ANALYST_REPORTS if kind == "stock" or r != "fundamentals_report.md"]
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
    p.add_argument("--dates", help="several trade dates, comma-separated (a backtest grid)")
    p.add_argument("--date-range", help="START:END:STEP_DAYS, e.g. 2026-07-01:2026-09-30:14 (a backtest grid)")
    p.add_argument("--no-settle", action="store_true", help="do not settle past decisions (keeps backtest cells independent)")
    p.add_argument("--data-dir", help="default: $TRADINGCLAWD_DIR, else ./.tradingclawd")
    p.add_argument("--debate-rounds", type=int, default=1)
    p.add_argument("--risk-rounds", type=int, default=1)
    p.add_argument("--start-at", choices=STAGES, default="analyze")
    p.add_argument("--stop-after", choices=STAGES, default="decide")
    p.add_argument("--analysts", help="comma-separated subset of market,social,news,fundamentals (default: all)")
    p.add_argument("--portfolio", help="JSON file with the caller's cash and positions (default: <data_dir>/portfolio.json if present)")
    p.add_argument("--language", default="English", help="language for the written reports (ratings stay in English)")
    args = p.parse_args()
    analysts = parse_analysts(args.analysts)

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
    trade_dates = parse_dates(args)
    trade_date = trade_dates[0] if len(trade_dates) == 1 else "multiple"
    tickers = parse_tickers(args.tickers)
    stages = list(STAGES[STAGES.index(args.start_at): STAGES.index(args.stop_after) + 1])
    # Later stages build on this one, so their old outputs go stale too.
    stale = list(STAGES[STAGES.index(args.start_at):])

    # Check every ticker before touching any of them.
    entries, problems = [], []
    for day in trade_dates:
        for t, user_symbol in tickers:
            kind = asset_type(t)
            results_dir = os.path.join(data_dir, "results", t, day)
            missing = missing_prerequisites(results_dir, args.start_at, kind)
            if missing:
                earlier = STAGES[STAGES.index(args.start_at) - 1]
                problems.append(f"{t}: missing {', '.join(missing)} in {results_dir} "
                                f"(run {SKILL_FOR_STAGE[earlier]} {t} {day} first)")
            entries.append({"ticker": t, "trade_date": day, "results_dir": results_dir, "asset_type": kind,
                            "user_symbol": user_symbol if user_symbol != t else None})
    if problems:
        fail("cannot start at '" + args.start_at + "':\n  " + "\n  ".join(problems))

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    identities = {}
    for e in entries:
        # Resolved once per ticker so every agent anchors to the same instrument.
        if e["ticker"] not in identities:
            identities[e["ticker"]] = resolve(e["ticker"])
        identity = identities[e["ticker"]]
        e["name"] = identity.get("name")
        e["instrument_context"] = instrument_context(e["ticker"], e["trade_date"], identity, e.pop("user_symbol"))
        os.makedirs(e["results_dir"], exist_ok=True)
        e["set_aside"] = set_aside_outputs(e["results_dir"], stale, stamp)
        for sub in ("debate_turns", "risk_turns"):
            os.makedirs(os.path.join(e["results_dir"], sub), exist_ok=True)

    book, portfolio_path = load_portfolio(args.portfolio, data_dir)
    for e in entries:
        e["portfolio_context"] = render_portfolio(book, e["ticker"])

    # Score past decisions whose holding window has traded, for the reflector that
    # runs beside the analysts; only a run that ends in a decision uses the lessons.
    settlements = {"due": [], "failed": [], "still_pending": 0}
    if "decide" in stages and not args.no_settle:
        import memory_log
        holding_days = int(os.environ.get("TRADINGCLAWD_HOLDING_DAYS") or 5)
        try:
            for line in memory_log.sweep(data_dir):
                print(f"[memory] {line} (decision on disk was missing from the log)", file=sys.stderr)
            settlements = memory_log.settle_due(data_dir, holding_days)
        except Exception as exc:  # never block a run on settling old decisions
            settlements["failed"].append({"ticker": "*", "trade_date": "*", "reason": str(exc)})

    def agents_for(kind: str) -> int:
        n_analysts = len([a for a in analysts if a != "fundamentals" or kind == "stock"])
        return ((n_analysts if "analyze" in stages else 0)
                + (2 * args.debate_rounds + 1 if "debate" in stages else 0)
                + (1 + 3 * args.risk_rounds + 1 if "decide" in stages else 0))
    print(json.dumps({
        "plugin_dir": plugin_dir,
        "data_dir": data_dir,
        "memory_log": os.path.join(data_dir, "memory", "trading_memory.md"),
        "trade_date": trade_date,
        "trade_dates": trade_dates,
        "debate_rounds": args.debate_rounds,
        "risk_rounds": args.risk_rounds,
        "start_at": args.start_at,
        "stop_after": args.stop_after,
        "analysts": analysts,
        "output_language": args.language.strip() or "English",
        "portfolio_file": portfolio_path,
        "agents_planned": sum(agents_for(e["asset_type"]) for e in entries) + (1 if settlements["due"] else 0),
        "tickers": entries,
        "settlements": settlements,
    }, indent=2))


if __name__ == "__main__":
    main()
