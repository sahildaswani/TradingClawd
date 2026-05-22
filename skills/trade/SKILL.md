---
name: trade
description: "Run the full TradingClawd multi-agent pipeline on one or more tickers and produce a portfolio decision (Buy / Overweight / Hold / Underweight / Sell) per ticker. Usage: `/trade NVDA` or `/trade NVDA,AAPL,TSLA` or `/trade NVDA 2026-05-22`."
argument-hint: "<ticker>[,<ticker>...] [trade-date YYYY-MM-DD]"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent
---

# /trade — multi-agent trading pipeline

## What this does

Runs the full pipeline (four analysts in parallel → bull/bear research debate → research manager → trader → aggressive/conservative/neutral risk debate → portfolio manager) for one or more tickers concurrently. Final decisions land at `${data_dir}/results/<TICKER>/<DATE>/portfolio_decision.json` and are appended to `${data_dir}/memory/trading_memory.md`.

## Arguments

Parse `$ARGUMENTS` as: `<ticker>[,<ticker>...] [<YYYY-MM-DD>]`.

- **tickers**: comma-separated list of stock symbols (e.g. `NVDA`, or `NVDA,AAPL,TSLA`). Uppercase them.
- **trade_date**: optional. If omitted, default to today's date (use `date +%Y-%m-%d` via Bash — do not invent a date).

If no tickers are provided, ask the user which ticker(s) they want before proceeding.

## Configuration defaults

- `max_debate_rounds` = 1
- `max_risk_discuss_rounds` = 1

## Steps

### 1. Resolve `plugin_dir`, `data_dir`, and `trade_date`

Run this Bash to resolve all three:

```bash
# plugin_dir — where the bundled Python data scripts live.
# Claude Code may export CLAUDE_PLUGIN_ROOT; otherwise probe the cache.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/_common.py" ]; then
  PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT}"
else
  PLUGIN_DIR=$(find "$HOME/.claude/plugins" -type f -name "_common.py" -path "*/tradingclawd/scripts/*" 2>/dev/null | head -1 | sed 's|/scripts/_common.py||')
  if [ -z "$PLUGIN_DIR" ] && [ -f "/Users/sahildaswani/Desktop/TradingClawd/scripts/_common.py" ]; then
    PLUGIN_DIR="/Users/sahildaswani/Desktop/TradingClawd"
  fi
fi

# data_dir — where results and the memory log are written.
# Env-var override → otherwise default to a project-local .tradingclawd/ in the cwd.
if [ -n "${TRADINGCLAWD_DIR:-}" ]; then
  DATA_DIR="${TRADINGCLAWD_DIR}"
else
  DATA_DIR="$(pwd)/.tradingclawd"
fi
mkdir -p "${DATA_DIR}"

TRADE_DATE=$(date +%Y-%m-%d)  # only used as default if user didn't pass one

echo "plugin_dir=${PLUGIN_DIR}"
echo "data_dir=${DATA_DIR}"
echo "trade_date=${TRADE_DATE}"
```

If `PLUGIN_DIR` ends up empty, stop and tell the user the TradingClawd plugin scripts could not be located — they may need to reinstall via `/plugin marketplace update tradingclawd-marketplace`.

Tell the user (one line) where results will be written, e.g.: `Writing to: ${DATA_DIR}/results/<TICKER>/<DATE>/`.

### 2. Spawn one `tradingclawd:ta-ticker-orchestrator` subagent per ticker IN PARALLEL

In a **single message**, call `Agent` once per ticker (so they run concurrently). Each subagent prompt should look like:

```
ticker: NVDA
trade_date: 2026-05-22
plugin_dir: <resolved plugin_dir>
data_dir: <resolved data_dir>
max_debate_rounds: 1
max_risk_discuss_rounds: 1

Drive the full TradingClawd pipeline for this ticker per your instructions and return the one-line summary when done.
```

Use `subagent_type: tradingclawd:ta-ticker-orchestrator` for each spawn. The `tradingclawd:` prefix is required — Claude Code namespaces plugin-supplied subagents by plugin name.

### 3. Print the summary table

When all orchestrators complete, collate their one-line returns into a markdown table and print it to the user:

```
| Ticker | Date       | Rating      | Summary                           |
|--------|------------|-------------|-----------------------------------|
| NVDA   | 2026-05-22 | Overweight  | <executive summary excerpt>       |
| AAPL   | 2026-05-22 | Hold        | <...>                             |
```

Tell the user the full per-ticker artifacts are in `${data_dir}/results/<TICKER>/<TRADE_DATE>/` and the running decision log is `${data_dir}/memory/trading_memory.md`.

## Rules

- Tickers run in parallel — DO NOT serialize them. One `Agent` tool call per ticker, all in one message.
- Do NOT run analyst/debate/trader logic yourself in the main skill context — delegate ALL of it to `tradingclawd:ta-ticker-orchestrator`. This keeps the main context small.
- Do NOT invent the current date — read it from the system.
- NEVER write under `${plugin_dir}` — that's the plugin install location (potentially read-only, gets overwritten on `/plugin marketplace update`). Results and memory always go under `${data_dir}`.
