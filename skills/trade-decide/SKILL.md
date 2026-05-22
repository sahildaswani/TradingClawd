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

### 1. Resolve `data_dir`

```bash
if [ -n "${TRADINGCLAWD_DIR:-}" ]; then
  DATA_DIR="${TRADINGCLAWD_DIR}"
else
  DATA_DIR="$(pwd)/.tradingclawd"
fi
```

### 2. Compute `results_dir` and verify research plan exists

```
results_dir = ${data_dir}/results/<TICKER>/<TRADE_DATE>
```

Verify `${results_dir}/research_plan.json` exists. If not, stop and tell the user to run `/trade-debate <ticker> [date]` first.

### 3. Trader phase

Spawn `tradingclawd:ta-trader` (subagent_type — the `tradingclawd:` prefix is required for all plugin-supplied subagents) with `{ticker, trade_date, results_dir}`. It writes `trader_proposal.json`.

### 4. Risk debate phase

`mkdir -p ${results_dir}/risk_turns`.

For `n` in 1..rounds:
   a. Spawn `tradingclawd:ta-risk-aggressive` with `{ticker, results_dir, round=n, risk_history}` (history is the concatenated contents of all prior files in `${results_dir}/risk_turns/`).
   b. Then `tradingclawd:ta-risk-conservative` with the updated history.
   c. Then `tradingclawd:ta-risk-neutral` with the updated history.

### 5. Portfolio Manager

Spawn `tradingclawd:ta-portfolio-manager` with `{ticker, trade_date, results_dir, data_dir}`. It writes `portfolio_decision.json` and incorporates prior-decision lessons from `${data_dir}/memory/trading_memory.md` if applicable.

### 6. Append to memory log

If `${data_dir}/memory/trading_memory.md` does not exist, create the `memory/` directory and the file with header `# TradingClawd decision log\n\n`. Then append:

```
## <trade_date> | <TICKER> | <rating> | pending
<executive_summary>

```

### 7. Print summary

Print to the user: `<TICKER> @ <trade_date>: <rating> — <one-sentence excerpt>` and the path to `portfolio_decision.json`.

## Rules

- NEVER write under `${plugin_dir}` — memory and results always go under `${data_dir}`.
