---
name: trade-analyze
description: "Run only the analyst phase of the TradingClawd pipeline (market + social + news + fundamentals) for one ticker. Writes four reports to results/<TICKER>/<DATE>/. Useful for refreshing data without re-running debates. Usage: `/trade-analyze NVDA [2026-05-22]`."
argument-hint: "<ticker> [trade-date YYYY-MM-DD]"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent
---

# /trade-analyze — analyst phase only

Runs the four analyst subagents in parallel for ONE ticker and stops. No research debate, no trader, no risk debate, no final decision.

## Arguments

Parse `$ARGUMENTS` as: `<ticker> [<YYYY-MM-DD>]`. Default `trade_date` to today (via `date +%Y-%m-%d`). If no ticker provided, ask.

## Steps

1. Resolve `plugin_dir` (default `/Users/sahildaswani/Desktop/TradingClawd`).
2. Compute `results_dir = ${plugin_dir}/results/<TICKER>/<TRADE_DATE>/`. Create it: `mkdir -p`.
3. **In a single message**, spawn the four analyst subagents in parallel:
   - `ta-market-analyst`
   - `ta-social-analyst`
   - `ta-news-analyst`
   - `ta-fundamentals-analyst`

   Each prompt should include `ticker`, `trade_date`, `results_dir`, `plugin_dir`.
4. When all four return, confirm the four report files exist and print a one-line summary per analyst (e.g. "market_report.md: 4.3 KB").

Tell the user the next step is `/trade-debate <ticker> [date]` to run the bull/bear research debate.
