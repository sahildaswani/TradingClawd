#!/usr/bin/env python3
"""The TradingClawd decision log: each decision as made and, once its holding
window has traded, its outcome and a short lesson. Lives at
${data_dir}/memory/trading_memory.md.

  memory_log.py store         --data-dir D --ticker T --trade-date YYYY-MM-DD --results-dir R
  memory_log.py show          --data-dir D --ticker T --trade-date YYYY-MM-DD
  memory_log.py settle-due    --data-dir D [--holding-days 5] [--max 10]
  memory_log.py apply-outcome --data-dir D --ticker T --trade-date YYYY-MM-DD --reflection-file F
  memory_log.py past-context  --data-dir D --ticker T --as-of YYYY-MM-DD

store        records R/portfolio_decision.json as a pending entry; a ticker already
             logged for that date is not logged again.
settle-due   scores every pending decision whose holding window has fully traded
             against its benchmark, and writes the figures to
             memory/settlements_due.json for the reflector.
apply-outcome  records a due decision's outcome (figures from settlements_due.json)
             and the reflection in F.
past-context the lessons a decision on --as-of may use: recent settled decisions
             for the ticker and lessons from others, only those known by that date.

Entry format (the same as upstream TradingAgents):

  [2026-10-14 | NVDA | Hold | pending]                      <- until settled
  [2026-10-14 | NVDA | Hold | +2.1% | -0.4% | 5d | resolved:2026-10-21]

  DECISION:
  ...
  REFLECTION:                                               <- once settled
  ...
  <!-- ENTRY_END -->
"""

import argparse
import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import die, parse_date, yf_retry

SEPARATOR = "\n\n<!-- ENTRY_END -->\n\n"
DECISION_RE = re.compile(r"DECISION:\n(.*?)(?=\nREFLECTION:|\Z)", re.DOTALL)
REFLECTION_RE = re.compile(r"REFLECTION:\n(.*?)$", re.DOTALL)
RATINGS = ("Buy", "Overweight", "Hold", "Underweight", "Sell")
OLD_TAG_RE = re.compile(r"^## (\d{4}-\d{2}-\d{2}) \| ([^|]+?) \| ([^|]+?) \| pending\s*$")

# Benchmark for alpha, by the ticker's exchange suffix (upstream's map). Returns are
# compared as percentages, each in its own currency.
BENCHMARKS = {
    ".NS": "^NSEI", ".BO": "^BSESN", ".T": "^N225", ".TW": "^TWII", ".TWO": "^TWII",
    ".KS": "^KS11", ".KQ": "^KQ11", ".HK": "^HSI", ".SI": "^STI", ".L": "^FTSE",
    ".DE": "^GDAXI", ".PA": "^FCHI", ".AS": "^AEX", ".SW": "^SSMI", ".MI": "FTSEMIB.MI",
    ".TO": "^GSPTSE", ".AX": "^AXJO", ".SS": "000001.SS", ".SZ": "399001.SZ", ".SA": "^BVSP",
}
DEFAULT_BENCHMARK = "SPY"


# --- Files and locking -----------------------------------------------------------


def paths(data_dir: str) -> dict:
    memory = os.path.join(data_dir, "memory")
    return {
        "dir": memory,
        "log": os.path.join(memory, "trading_memory.md"),
        "lock": os.path.join(memory, ".trading_memory.lock"),
        "due": os.path.join(memory, "settlements_due.json"),
        "reflections": os.path.join(memory, "reflections"),
    }


@contextmanager
def locked(data_dir: str):
    """Hold the log for one read-modify-write; parallel managers may finish at once."""
    p = paths(data_dir)
    os.makedirs(p["dir"], exist_ok=True)
    with open(p["lock"], "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield p
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def _read(log_path: str) -> str:
    try:
        with open(log_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _write(log_path: str, text: str) -> None:
    tmp = log_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, log_path)  # a crash mid-write never leaves a half-written log


def _migrate(log_path: str, text: str) -> str:
    """Convert the pre-0.7 log (`## date | T | rating | pending` + summary) in place,
    keeping a copy of the original beside it."""
    if not any(OLD_TAG_RE.match(line) for line in text.splitlines()):
        return text
    blocks, current = [], None
    for line in text.splitlines():
        m = OLD_TAG_RE.match(line)
        if m:
            current = {"date": m.group(1), "ticker": m.group(2).strip(), "rating": m.group(3).strip(), "body": []}
            blocks.append(current)
        elif current is not None:
            current["body"].append(line)
    migrated = "".join(
        f"[{b['date']} | {b['ticker']} | {b['rating']} | pending]\n\nDECISION:\n"
        f"**Executive Summary**: {chr(10).join(b['body']).strip()}{SEPARATOR}"
        for b in blocks
    )
    backup = f"{log_path}.pre-0.7-{datetime.now():%Y%m%d-%H%M%S}"
    with open(backup, "w", encoding="utf-8") as f:
        f.write(text)
    _write(log_path, migrated)
    print(f"[migrated] {len(blocks)} entries to the new log format; original kept at {backup}", file=sys.stderr)
    return migrated


def load(data_dir: str) -> tuple[str, list[dict]]:
    """The log text (migrated if needed) and its parsed entries. Call under the lock."""
    log_path = paths(data_dir)["log"]
    text = _migrate(log_path, _read(log_path))
    entries = []
    for raw in (e.strip() for e in text.split(SEPARATOR)):
        if raw:
            entry = _parse(raw)
            if entry:
                entries.append(entry)
    return text, entries


def _parse(raw: str) -> dict | None:
    lines = raw.splitlines()
    tag = lines[0].strip()
    if not (tag.startswith("[") and tag.endswith("]")):
        return None
    fields = [f.strip() for f in tag[1:-1].split("|")]
    if len(fields) < 4:
        return None
    body = "\n".join(lines[1:]).strip()
    decision, reflection = DECISION_RE.search(body), REFLECTION_RE.search(body)
    resolved = next((f[len("resolved:"):] for f in fields[6:] if f.startswith("resolved:")), None)
    return {
        "date": fields[0], "ticker": fields[1], "rating": fields[2],
        "pending": fields[3] == "pending",
        "raw": None if fields[3] == "pending" else fields[3],
        "alpha": fields[4] if len(fields) > 4 else None,
        "holding": fields[5] if len(fields) > 5 else None,
        "resolved": resolved,
        "decision": decision.group(1).strip() if decision else "",
        "reflection": reflection.group(1).strip() if reflection else "",
    }


def _find(entries, ticker: str, trade_date: str) -> dict | None:
    return next((e for e in entries if e["ticker"] == ticker and e["date"] == trade_date), None)


# --- store / show ----------------------------------------------------------------


def render_decision(d: dict) -> str:
    def opt(v):
        return "not provided" if v in (None, "") else v
    return "\n\n".join([
        f"**Rating**: {d.get('rating')}",
        f"**Executive Summary**: {(d.get('executive_summary') or '').strip()}",
        f"**Investment Thesis**: {(d.get('investment_thesis') or '').strip()}",
        f"**Price Target**: {opt(d.get('price_target'))}",
        f"**Time Horizon**: {opt(d.get('time_horizon'))}",
    ])


def store(data_dir: str, ticker: str, trade_date: str, results_dir: str) -> str:
    ticker = ticker.upper()
    decision_path = os.path.join(results_dir, "portfolio_decision.json")
    try:
        with open(decision_path, encoding="utf-8") as f:
            decision = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        die(f"cannot read {decision_path}: {exc}")
    rating = decision.get("rating") if decision.get("rating") in RATINGS else "REVIEW"
    entry = f"[{trade_date} | {ticker} | {rating} | pending]\n\nDECISION:\n{render_decision(decision)}"
    with locked(data_dir) as p:
        text, entries = load(data_dir)
        # One entry per ticker and date, so no decision is counted twice. A re-run
        # replaces a decision that is still pending; a settled one is history.
        existing = _find(entries, ticker, trade_date)
        if existing and not existing["pending"]:
            return f"already settled, not replaced: {ticker} {trade_date}"
        if existing:
            prefix = f"[{trade_date} | {ticker} |"
            blocks = text.split(SEPARATOR)
            for i, block in enumerate(blocks):
                if block.strip().startswith(prefix):
                    blocks[i] = entry
                    break
            _write(p["log"], SEPARATOR.join(blocks))
            return f"replaced pending entry: {ticker} {trade_date} {rating}"
        _write(p["log"], text + entry + SEPARATOR)
    return f"logged: {ticker} {trade_date} {rating}"


def sweep(data_dir: str) -> list[str]:
    """Log decisions on disk that the log does not have (a manager that wrote its
    decision but never recorded it). Pending and settled entries are left alone."""
    import glob

    with locked(data_dir):
        _, entries = load(data_dir)
    known = {(e["ticker"], e["date"]) for e in entries}
    logged = []
    for path in sorted(glob.glob(os.path.join(data_dir, "results", "*", "*", "portfolio_decision.json"))):
        results_dir = os.path.dirname(path)
        trade_date, ticker = os.path.basename(results_dir), os.path.basename(os.path.dirname(results_dir))
        if (ticker, trade_date) not in known:
            logged.append(store(data_dir, ticker, trade_date, results_dir))
    return logged


def show(data_dir: str, ticker: str, trade_date: str) -> str:
    with locked(data_dir):
        _, entries = load(data_dir)
    e = _find(entries, ticker.upper(), trade_date)
    if not e:
        die(f"no log entry for {ticker.upper()} {trade_date}")
    return f"[{e['date']} | {e['ticker']} | {e['rating']}]\n\n{e['decision']}"


# --- Settlement ------------------------------------------------------------------


def benchmark_for(ticker: str) -> str:
    t = ticker.upper()
    for suffix in sorted(BENCHMARKS, key=len, reverse=True):
        if t.endswith(suffix):
            return BENCHMARKS[suffix]
    return DEFAULT_BENCHMARK


def _closes(symbol: str, start: str, end: str):
    """Daily closes keyed by exchange-local date, and today's date on that exchange."""
    import pandas as pd
    import yfinance as yf

    hist = yf_retry(lambda: yf.Ticker(symbol).history(start=start, end=end, auto_adjust=True))
    if hist is None or hist.empty or "Close" not in hist.columns:
        return pd.Series(dtype=float), None
    today = pd.Timestamp.now(tz=hist.index.tz).normalize()
    closes = hist["Close"]
    if closes.index.tz is not None:
        closes.index = closes.index.tz_localize(None)
        today = today.tz_localize(None)
    closes.index = closes.index.normalize()
    return closes[closes > 0].dropna(), today


def fetch_returns(ticker: str, trade_date: str, holding_days: int, benchmark: str):
    """(raw, alpha, resolution_date) once the full holding window has traded, else None.

    Entry is the first close on or after the trade date; exit is ``holding_days``
    sessions later. The exit session must be over (not today's bar, which may still
    be trading), and the benchmark must have traded through it, so a decision is
    never scored on a partial window.
    """
    start = parse_date(trade_date)
    # holding_days counts sessions; ask for the calendar span they take plus a week.
    end = (start + timedelta(days=round(holding_days * 7 / 5) + 7)).strftime("%Y-%m-%d")
    stock, today = _closes(ticker, trade_date, end)
    if len(stock) <= holding_days:
        return None
    entry, exit_ = stock.index[0], stock.index[holding_days]
    if today is not None and exit_ >= today:
        return None
    bench, _ = _closes(benchmark, (start - timedelta(days=7)).strftime("%Y-%m-%d"), end)
    if bench.empty or bench.index[0] > entry or bench.index[-1] < exit_:
        return None
    raw = float(stock.iloc[holding_days] / stock.iloc[0] - 1)
    bench_ret = float(bench.asof(exit_) / bench.asof(entry) - 1)
    return raw, raw - bench_ret, exit_.strftime("%Y-%m-%d")


def settle_due(data_dir: str, holding_days: int = 5, max_items: int = 10) -> dict:
    """Score pending decisions whose holding window has traded; write settlements_due.json."""
    p = paths(data_dir)
    with locked(data_dir):
        _, entries = load(data_dir)
    pending = [e for e in entries if e["pending"]]
    today = datetime.now()
    due, failed, waiting = [], [], 0
    for e in pending:
        # A window of N sessions needs at least N weekdays after the trade date.
        if (today - parse_date(e["date"])).days < holding_days:
            waiting += 1
            continue
        if len(due) >= max_items:
            waiting += 1
            continue
        benchmark = benchmark_for(e["ticker"])
        try:
            outcome = fetch_returns(e["ticker"], e["date"], holding_days, benchmark)
        except Exception as exc:  # a vendor failure leaves the entry pending for next time
            failed.append({"ticker": e["ticker"], "trade_date": e["date"], "reason": f"prices unavailable: {exc}"})
            continue
        if outcome is None:
            waiting += 1
            continue
        raw, alpha, resolved = outcome
        due.append({
            "ticker": e["ticker"], "trade_date": e["date"], "rating": e["rating"],
            "raw_return": round(raw, 6), "alpha_return": round(alpha, 6), "benchmark": benchmark,
            "holding_days": holding_days, "resolution_date": resolved,
        })
    if due or os.path.exists(p["due"]):
        os.makedirs(p["dir"], exist_ok=True)
        with open(p["due"], "w", encoding="utf-8") as f:
            json.dump(due, f, indent=2)
    return {"due": due, "failed": failed, "still_pending": waiting}


def apply_outcome(data_dir: str, ticker: str, trade_date: str, reflection_file: str) -> str:
    ticker = ticker.upper()
    try:
        with open(reflection_file, encoding="utf-8") as f:
            reflection = f.read().strip()
    except OSError as exc:
        die(f"cannot read {reflection_file}: {exc}")
    if not reflection:
        die(f"{reflection_file} is empty")
    with locked(data_dir) as p:
        try:
            with open(p["due"], encoding="utf-8") as f:
                due = json.load(f)
        except (OSError, json.JSONDecodeError):
            die(f"no settlement figures in {p['due']}; run settle-due first")
        item = next((d for d in due if d["ticker"] == ticker and d["trade_date"] == trade_date), None)
        text, entries = load(data_dir)
        if item is None:
            settled = _find(entries, ticker, trade_date)
            if settled and not settled["pending"]:
                return f"already settled: {ticker} {trade_date}"
            die(f"{ticker} {trade_date} is not in {p['due']}")
        prefix = f"[{trade_date} | {ticker} |"
        blocks = text.split(SEPARATOR)
        for i, block in enumerate(blocks):
            lines = block.strip().splitlines()
            if lines and lines[0].startswith(prefix) and lines[0].endswith("| pending]"):
                rating = [f.strip() for f in lines[0][1:-1].split("|")][2]
                tag = (f"[{trade_date} | {ticker} | {rating} | {item['raw_return']:+.1%} | "
                       f"{item['alpha_return']:+.1%} | {item['holding_days']}d | "
                       f"resolved:{item['resolution_date']}]")
                rest = "\n".join(lines[1:]).strip()
                blocks[i] = f"{tag}\n\n{rest}\n\nREFLECTION:\n{reflection}"
                _write(p["log"], SEPARATOR.join(blocks))
                break
        else:
            return f"not pending (already settled?): {ticker} {trade_date}"
        remaining = [d for d in due if d is not item]
        with open(p["due"], "w", encoding="utf-8") as f:
            json.dump(remaining, f, indent=2)
    return f"settled: {ticker} {trade_date} {item['raw_return']:+.1%} (alpha {item['alpha_return']:+.1%} vs {item['benchmark']})"


# --- Past context ----------------------------------------------------------------


def past_context(data_dir: str, ticker: str, as_of: str, n_same: int = 5, n_cross: int = 3) -> str:
    """Lessons whose outcome was known by ``as_of``: the ticker's recent settled
    decisions in full, plus reflections from other tickers."""
    ticker = ticker.upper()
    with locked(data_dir):
        _, entries = load(data_dir)
    settled = [e for e in entries if not e["pending"] and e["resolved"] and e["resolved"] <= as_of]
    same, cross = [], []
    for e in reversed(settled):
        if e["ticker"] == ticker and len(same) < n_same:
            same.append(e)
        elif e["ticker"] != ticker and len(cross) < n_cross:
            cross.append(e)
    if not same and not cross:
        return f"No settled past decisions known by {as_of}; base the decision solely on the current analysis."
    parts = []
    if same:
        parts.append(f"Past decisions on {ticker} (most recent first):")
        for e in same:
            parts.append(f"[{e['date']} | {e['ticker']} | {e['rating']} | return {e['raw']} | "
                         f"alpha {e['alpha']} | {e['holding']}]\nDECISION:\n{e['decision']}\nREFLECTION:\n{e['reflection']}")
    if cross:
        parts.append("Recent lessons from other tickers:")
        for e in cross:
            parts.append(f"[{e['date']} | {e['ticker']} | {e['rating']} | return {e['raw']}]\n{e['reflection']}")
    return "\n\n".join(parts)


# --- CLI -------------------------------------------------------------------------


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)

    def cmd(name, *extra):
        s = sub.add_parser(name)
        s.add_argument("--data-dir", required=True)
        for flag in extra:
            s.add_argument(flag, required=True)
        return s

    cmd("store", "--ticker", "--trade-date", "--results-dir")
    cmd("show", "--ticker", "--trade-date")
    sd = cmd("settle-due")
    sd.add_argument("--holding-days", type=int, default=5)
    sd.add_argument("--max", type=int, default=10)
    cmd("apply-outcome", "--ticker", "--trade-date", "--reflection-file")
    cmd("past-context", "--ticker", "--as-of")
    a = p.parse_args()

    if a.command == "store":
        print(store(a.data_dir, a.ticker, a.trade_date, a.results_dir))
    elif a.command == "show":
        print(show(a.data_dir, a.ticker, a.trade_date))
    elif a.command == "settle-due":
        print(json.dumps(settle_due(a.data_dir, a.holding_days, a.max), indent=2))
    elif a.command == "apply-outcome":
        print(apply_outcome(a.data_dir, a.ticker, a.trade_date, a.reflection_file))
    else:
        print(past_context(a.data_dir, a.ticker, a.as_of))


if __name__ == "__main__":
    main()
