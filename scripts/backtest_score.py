#!/usr/bin/env python3
"""Score a backtest: how each logged decision's direction compares with what the
price then did over the holding window.

  backtest_score.py --data-dir D [--holding-days 5]

Reads D/memory/trading_memory.md (the backtest's own log), measures every decision
whose window has traded against its benchmark, and writes D/backtest_summary.md.
Buy and Overweight claim the price will rise, Sell and Underweight that it will
fall; a decision is a hit when the return has the sign it claimed. Hold claims no
direction, so it has no hit rate. This evaluates decisions, not a portfolio: no
fills, sizes or compounding are simulated.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import die
from memory_log import benchmark_for, fetch_returns, load, locked

DIRECTION = {"Buy": 1, "Overweight": 1, "Hold": 0, "Underweight": -1, "Sell": -1}


def score(data_dir: str, holding_days: int) -> str:
    with locked(data_dir):
        _, entries = load(data_dir)
    if not entries:
        return f"No decisions in {os.path.join(data_dir, 'memory', 'trading_memory.md')} to score."
    cells, unscored = [], []
    for e in sorted(entries, key=lambda e: (e["date"], e["ticker"])):
        if e["rating"] not in DIRECTION:
            unscored.append(f"{e['ticker']} {e['date']}: rating {e['rating']} is not a call")
            continue
        try:
            outcome = fetch_returns(e["ticker"], e["date"], holding_days, benchmark_for(e["ticker"]))
        except Exception as exc:
            unscored.append(f"{e['ticker']} {e['date']}: prices unavailable ({exc})")
            continue
        if outcome is None:
            unscored.append(f"{e['ticker']} {e['date']}: the {holding_days}-day window has not fully traded yet")
            continue
        raw, alpha, _ = outcome
        d = DIRECTION[e["rating"]]
        cells.append({"ticker": e["ticker"], "date": e["date"], "rating": e["rating"], "dir": d,
                      "raw": raw, "alpha": alpha, "hit": None if d == 0 else (raw * d > 0),
                      "alpha_hit": None if d == 0 else (alpha * d > 0)})

    def pct(x):
        return f"{x:+.1%}"

    def rate(xs):
        xs = [x for x in xs if x is not None]
        return f"{sum(xs)}/{len(xs)} ({sum(xs) / len(xs):.0%})" if xs else "n/a"

    lines = [f"# Backtest summary ({holding_days}-day holding window)", "",
             f"- Decisions scored: {len(cells)} of {len(entries)}", ""]
    if cells:
        directional = [c for c in cells if c["dir"] != 0]
        lines += [f"- Directional hit rate (return had the claimed sign): {rate([c['hit'] for c in directional])}",
                  f"- Alpha hit rate (beat or lagged the benchmark as claimed): {rate([c['alpha_hit'] for c in directional])}",
                  (f"- Mean signed alpha (alpha x claimed direction, a long/short proxy): "
                   f"{pct(sum(c['alpha'] * c['dir'] for c in directional) / len(directional))}" if directional else
                   "- Mean signed alpha: n/a (no directional calls)"), "",
                  "## By rating", "", "| Rating | Count | Mean return | Mean alpha | Hit rate |", "|---|---:|---:|---:|---:|"]
        for rating in DIRECTION:
            rs = [c for c in cells if c["rating"] == rating]
            if rs:
                lines.append(f"| {rating} | {len(rs)} | {pct(sum(c['raw'] for c in rs) / len(rs))} | "
                             f"{pct(sum(c['alpha'] for c in rs) / len(rs))} | {rate([c['hit'] for c in rs])} |")
        lines += ["", "## Every decision", "", "| Date | Ticker | Rating | Return | Alpha | Hit |", "|---|---|---|---:|---:|---|"]
        for c in cells:
            hit = "n/a" if c["hit"] is None else ("yes" if c["hit"] else "no")
            lines.append(f"| {c['date']} | {c['ticker']} | {c['rating']} | {pct(c['raw'])} | {pct(c['alpha'])} | {hit} |")
    if unscored:
        lines += ["", "## Not scored", ""] + [f"- {u}" for u in unscored]
    lines += ["", "A few dozen decisions over one market regime say little about skill; read hit rates with their counts."]
    return "\n".join(lines) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--holding-days", type=int, default=int(os.environ.get("TRADINGCLAWD_HOLDING_DAYS") or 5))
    args = p.parse_args()
    try:
        summary = score(args.data_dir, args.holding_days)
    except Exception as e:
        die(str(e))
    path = os.path.join(args.data_dir, "backtest_summary.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(summary)
    print(summary + f"\nwritten: {path}")


if __name__ == "__main__":
    main()
