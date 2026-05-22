---
name: trade-debate
description: "Run only the bull/bear research debate + research manager for one ticker. Assumes analyst reports already exist in ${data_dir}/results/<TICKER>/<DATE>/. Usage: `/trade-debate NVDA [2026-05-22] [rounds=1]`."
argument-hint: "<ticker> [trade-date YYYY-MM-DD] [rounds=N]"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent
---

# /trade-debate — research debate only

Runs the bull/bear debate (configurable rounds) for ONE ticker, then has the research manager produce `research_plan.json`. Requires the four analyst reports to already exist on disk.

## Arguments

Parse `$ARGUMENTS` as: `<ticker> [<YYYY-MM-DD>] [rounds=N]`. Default `trade_date` to today, default `rounds=1`.

## Steps

### 1. Resolve `data_dir`

```bash
if [ -n "${TRADINGCLAWD_DIR:-}" ]; then
  DATA_DIR="${TRADINGCLAWD_DIR}"
else
  DATA_DIR="$(pwd)/.tradingclawd"
fi
```

### 2. Compute `results_dir` and verify analyst reports exist

```
results_dir = ${data_dir}/results/<TICKER>/<TRADE_DATE>
```

Verify all four files exist in `${results_dir}/`: `market_report.md`, `sentiment_report.md`, `news_report.md`, `fundamentals_report.md`. If any are missing, stop and tell the user to run `/trade-analyze <ticker> [date]` first (and remind them to set `TRADINGCLAWD_DIR` if they used it before).

### 3. Debate loop

`mkdir -p ${results_dir}/debate_turns`.

For `n` in 1..rounds (use `subagent_type` values with the `tradingclawd:` prefix exactly as shown):
   a. Spawn `tradingclawd:ta-bull-researcher` with `{ticker, results_dir, round=n, debate_history}`. The `debate_history` is the concatenation of every previously-written file in `${results_dir}/debate_turns/` in order — include its actual contents in the prompt, not just file paths.
   b. After bull_<n>.md exists, spawn `tradingclawd:ta-bear-researcher` with the updated history.

### 4. Research Manager

After the loop, spawn `tradingclawd:ta-research-manager` with `{ticker, trade_date, results_dir}`. It writes `research_plan.json`.

### 5. Summarize

Read `research_plan.json` and print a 2-line summary: the `recommendation` and the first ~30 words of `rationale`. Tell the user the next step is `/trade-decide <ticker> [date]` to run the trader + risk debate + portfolio manager.
