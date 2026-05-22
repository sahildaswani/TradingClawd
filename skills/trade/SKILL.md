---
name: trade
description: "Run the full TradingClawd multi-agent pipeline on one or more tickers and produce a portfolio decision (Buy / Overweight / Hold / Underweight / Sell) per ticker. Usage: `/trade NVDA` or `/trade NVDA,AAPL,TSLA` or `/trade NVDA 2026-05-22`."
argument-hint: "<ticker>[,<ticker>...] [trade-date YYYY-MM-DD]"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent
---

# /trade — multi-agent trading pipeline

## What this does

Runs the full pipeline (four analysts in parallel → bull/bear research debate → research manager → trader → aggressive/conservative/neutral risk debate → portfolio manager) for one or more tickers concurrently. Final decisions are written to `results/<TICKER>/<DATE>/portfolio_decision.json` and appended to `memory/trading_memory.md`.

## Arguments

Parse `$ARGUMENTS` as: `<ticker>[,<ticker>...] [<YYYY-MM-DD>]`.

- **tickers**: comma-separated list of stock symbols (e.g. `NVDA`, or `NVDA,AAPL,TSLA`). Uppercase them.
- **trade_date**: optional. If omitted, default to **today's date** (use `date +%Y-%m-%d` via Bash to get it — do not invent a date).

If no tickers are provided, ask the user which ticker(s) they want before proceeding.

## Configuration defaults

- `max_debate_rounds` = 1
- `max_risk_discuss_rounds` = 1
- `plugin_dir` = the absolute path of the TradingClawd plugin root (the directory containing `.claude-plugin/`, `agents/`, `scripts/`). Resolve it once at the start using `realpath` on this skill file's directory's parent's parent, or hard-fall back to `/Users/sahildaswani/Desktop/TradingClawd` if running locally.

## Steps

### 1. Resolve plugin_dir and trade_date

```bash
# Resolve plugin_dir: this SKILL.md lives at <plugin_dir>/skills/trade/SKILL.md
# In an installed plugin, the canonical location is under ~/.claude/plugins/...
# In dev, it's /Users/sahildaswani/Desktop/TradingClawd.
# Use this fallback: if /Users/sahildaswani/Desktop/TradingClawd/scripts/_common.py exists, use that.
test -f /Users/sahildaswani/Desktop/TradingClawd/scripts/_common.py && \
  PLUGIN_DIR=/Users/sahildaswani/Desktop/TradingClawd

# Fallback to today's date if not provided
TRADE_DATE=$(date +%Y-%m-%d)  # or whatever the user passed
```

If you cannot resolve the plugin directory deterministically, ask the user where TradingClawd is installed.

### 2. Spawn one `ta-ticker-orchestrator` subagent per ticker IN PARALLEL

In a **single message**, call `Agent` once per ticker (so they run concurrently). Pass each subagent a self-contained prompt like:

```
ticker: NVDA
trade_date: 2026-05-22
plugin_dir: /Users/sahildaswani/Desktop/TradingClawd
results_dir: /Users/sahildaswani/Desktop/TradingClawd/results/NVDA/2026-05-22
max_debate_rounds: 1
max_risk_discuss_rounds: 1

Drive the full TradingClawd pipeline for this ticker per your instructions and return the one-line summary when done.
```

Use `subagent_type: ta-ticker-orchestrator` for each spawn.

### 3. Print the summary table

When all orchestrators complete, collate their one-line returns into a markdown table and print it to the user:

```
| Ticker | Date       | Rating      | Summary                           |
|--------|------------|-------------|-----------------------------------|
| NVDA   | 2026-05-22 | Overweight  | <executive summary excerpt>       |
| AAPL   | 2026-05-22 | Hold        | <...>                             |
```

Tell the user the full per-ticker artifacts (analyst reports, debate turns, JSON outputs) are in `${plugin_dir}/results/<TICKER>/<TRADE_DATE>/`.

## Rules

- Tickers run in parallel — DO NOT serialize them. One `Agent` tool call per ticker, all in one message.
- Do NOT run analyst/debate/trader logic yourself in the main skill context — delegate ALL of it to `ta-ticker-orchestrator`. This keeps the main context small.
- Do NOT invent the current date — read it from the system.
