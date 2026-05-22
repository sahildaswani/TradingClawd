---
name: trade-decide
description: "Run the trader + risk debate + portfolio manager phases for one ticker. Assumes research_plan.json already exists. Usage: `/trade-decide NVDA [2026-05-22] [rounds=1]`."
argument-hint: "<ticker> [trade-date YYYY-MM-DD] [rounds=N]"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent
---

# /trade-decide — trader + risk debate + final decision

Picks up where `/trade-debate` left off: runs the trader, then the three risk debators (aggressive → conservative → neutral) for configurable rounds, then the portfolio manager. Appends to the memory log.

## Arguments

Parse `$ARGUMENTS` as: `<ticker> [<YYYY-MM-DD>] [rounds=N]`. Default `trade_date` to today, default `rounds=1`.

## Steps

1. Resolve `plugin_dir` and compute `results_dir`.
2. **Verify `${results_dir}/research_plan.json` exists.** If not, stop and tell the user to run `/trade-debate <ticker> [date]` first.
3. Spawn `ta-trader` (subagent_type) with `{ticker, trade_date, results_dir}`. It writes `trader_proposal.json`.
4. `mkdir -p ${results_dir}/risk_turns`.
5. **Risk debate loop** for `n` in 1..rounds:
   a. Spawn `ta-risk-aggressive` with `{ticker, results_dir, round=n, risk_history}` (history is the concatenated contents of all prior files in `${results_dir}/risk_turns/`).
   b. Then `ta-risk-conservative` with the updated history.
   c. Then `ta-risk-neutral` with the updated history.
6. Spawn `ta-portfolio-manager` with `{ticker, trade_date, results_dir, plugin_dir}`. It writes `portfolio_decision.json` and incorporates prior-decision lessons from `${plugin_dir}/memory/trading_memory.md` if applicable.
7. **Append to memory log.** If `${plugin_dir}/memory/trading_memory.md` does not exist, create it with header `# TradingClawd decision log\n\n`. Then append:
   ```
   ## <trade_date> | <TICKER> | <rating> | pending
   <executive_summary>

   ```
8. Print to the user: `<TICKER> @ <trade_date>: <rating> — <one-sentence excerpt>` and the path to `portfolio_decision.json`.
