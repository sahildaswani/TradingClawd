---
name: trade
description: "Run the full TradingClawd multi-agent pipeline on one or more tickers and produce a portfolio decision (Buy / Overweight / Hold / Underweight / Sell) per ticker. Usage: `/trade NVDA` or `/trade NVDA,AAPL,TSLA` or `/trade NVDA 2026-05-22`."
argument-hint: "<ticker>[,<ticker>...] [trade-date YYYY-MM-DD]"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent
---

# /trade — multi-agent trading pipeline

## What this does

Runs the full pipeline (four analysts in parallel → bull/bear research debate → research manager → trader → aggressive/conservative/neutral risk debate → portfolio manager) for one or more tickers. Multi-ticker runs are parallelized **wave by wave**: each phase spawns its subagents for all tickers in a single parallel batch, then the next phase begins once that wave completes.

Final decisions land at `${data_dir}/results/<TICKER>/<DATE>/portfolio_decision.json` and are appended to `${data_dir}/memory/trading_memory.md`.

## Arguments

Parse `$ARGUMENTS` as: `<ticker>[,<ticker>...] [<YYYY-MM-DD>]`.

- **tickers**: comma-separated list of stock symbols (e.g. `NVDA`, or `NVDA,AAPL,TSLA`). Uppercase them.
- **trade_date**: optional. If omitted, default to today's date (use `date +%Y-%m-%d` via Bash — do not invent a date).

If no tickers are provided, ask the user which ticker(s) they want before proceeding.

## Configuration defaults

- `max_debate_rounds` = 1 (one bull/bear exchange)
- `max_risk_discuss_rounds` = 1 (one aggressive/conservative/neutral cycle)

## Step 0: Resolve paths

```bash
# plugin_dir — where the bundled Python data scripts live.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/_common.py" ]; then
  PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT}"
else
  PLUGIN_DIR=$(find "$HOME/.claude/plugins" -type f -name "_common.py" -path "*/tradingclawd/scripts/*" 2>/dev/null | head -1 | sed 's|/scripts/_common.py||')
fi

# data_dir — where results and the memory log are written.
if [ -n "${TRADINGCLAWD_DIR:-}" ]; then
  DATA_DIR="${TRADINGCLAWD_DIR}"
else
  DATA_DIR="$(pwd)/.tradingclawd"
fi
mkdir -p "${DATA_DIR}"

TRADE_DATE=$(date +%Y-%m-%d)  # use this if user didn't pass one

echo "plugin_dir=${PLUGIN_DIR}"
echo "data_dir=${DATA_DIR}"
echo "trade_date=${TRADE_DATE}"
```

If `PLUGIN_DIR` is empty, stop and tell the user to reinstall the plugin via `/plugin marketplace update tradingclawd-marketplace`.

Tell the user (one line) where results will be written, e.g. `Writing to: ${DATA_DIR}/results/<TICKER>/<DATE>/`.

## Step 1: Create per-ticker results directories

For each ticker T in the list:
```bash
mkdir -p "${DATA_DIR}/results/${T}/${TRADE_DATE}/debate_turns"
mkdir -p "${DATA_DIR}/results/${T}/${TRADE_DATE}/risk_turns"
```

Let `results_dir(T) = ${DATA_DIR}/results/${T}/${TRADE_DATE}`. You'll use this path repeatedly below.

## Wave 1: Analyst phase (parallel across tickers × analyst types)

**In a single message**, spawn `N × 4` subagents — one of each analyst type per ticker. For N tickers this is up to 4N parallel `Agent` calls in one tool-use batch.

Subagent types to use (the `tradingclawd:` prefix is required):

- `tradingclawd:ta-market-analyst`
- `tradingclawd:ta-social-analyst`
- `tradingclawd:ta-news-analyst`
- `tradingclawd:ta-fundamentals-analyst`

Each subagent prompt should include `ticker`, `trade_date`, `results_dir`, `plugin_dir` for that specific ticker.

Wait for all of them to finish. Verify each ticker's `results_dir(T)/` now has `market_report.md`, `sentiment_report.md`, `news_report.md`, `fundamentals_report.md`.

## Wave 2: Research debate (sequential turns, parallel across tickers per turn)

For `n` in 1..`max_debate_rounds`:

**Wave 2.n.a — Bull turn:** For each ticker, build the `debate_history` string (concatenated contents of every prior turn file in `results_dir(T)/debate_turns/`, in lexical order). Then in a single message, spawn `tradingclawd:ta-bull-researcher` for every ticker in parallel. Each subagent gets `{ticker, results_dir, round=n, debate_history}` — the debate_history is that ticker's own history, not a shared string.

**Wave 2.n.b — Bear turn:** After all bull turns finish, rebuild each ticker's `debate_history` (now including `bull_<n>.md`). In a single message, spawn `tradingclawd:ta-bear-researcher` for every ticker in parallel with the updated history.

After all `max_debate_rounds` rounds complete, move on to Wave 3.

## Wave 3: Research Manager (parallel across tickers)

In one message, spawn `tradingclawd:ta-research-manager` for every ticker in parallel. Each gets `{ticker, trade_date, results_dir}`. Each writes `research_plan.json` into its ticker's `results_dir`.

## Wave 4: Trader (parallel across tickers)

In one message, spawn `tradingclawd:ta-trader` for every ticker in parallel. Each gets `{ticker, trade_date, results_dir}`. Each writes `trader_proposal.json`.

## Wave 5: Risk debate (sequential triads, parallel across tickers per turn)

For `n` in 1..`max_risk_discuss_rounds`:

**Wave 5.n.a — Aggressive:** For each ticker, build its `risk_history` (concatenated contents of `results_dir(T)/risk_turns/` in lexical order — empty for round 1). In one message, spawn `tradingclawd:ta-risk-aggressive` for every ticker in parallel.

**Wave 5.n.b — Conservative:** Rebuild each ticker's history. Spawn `tradingclawd:ta-risk-conservative` for every ticker in parallel (one message).

**Wave 5.n.c — Neutral:** Rebuild histories. Spawn `tradingclawd:ta-risk-neutral` for every ticker in parallel (one message).

## Wave 6: Portfolio Manager (parallel across tickers)

In one message, spawn `tradingclawd:ta-portfolio-manager` for every ticker in parallel. Each gets `{ticker, trade_date, results_dir, data_dir}` (the portfolio manager reads `${data_dir}/memory/trading_memory.md` for prior-decision lessons).

Each writes `portfolio_decision.json` to its `results_dir`.

## Step 7: Memory log append

For each ticker, read `results_dir(T)/portfolio_decision.json`. Then append to `${DATA_DIR}/memory/trading_memory.md`:

```
## <trade_date> | <TICKER> | <rating> | pending
<executive_summary>

```

If `${DATA_DIR}/memory/trading_memory.md` does not exist, first `mkdir -p ${DATA_DIR}/memory` and create the file with header `# TradingClawd decision log\n\n`.

## Step 8: Print summary table

Collate per-ticker decisions into a markdown table:

```
| Ticker | Date       | Rating      | Summary                           |
|--------|------------|-------------|-----------------------------------|
| NVDA   | 2026-05-22 | Overweight  | <executive summary excerpt>       |
| AAPL   | 2026-05-22 | Hold        | <…>                               |
```

Tell the user the per-ticker artifacts are in `${DATA_DIR}/results/<TICKER>/<TRADE_DATE>/` and the running decision log is `${DATA_DIR}/memory/trading_memory.md`.

## Rules

- **Parallelism is achieved within each wave, not across waves.** Wave K+1 cannot start until every subagent in Wave K has returned. This is enforced naturally by Claude Code — the next message in your turn happens after all parallel `Agent` calls return.
- **All `Agent` calls within a wave MUST be in a single message** so they execute concurrently. Separating them across messages serializes the wave.
- **Do NOT invent the current date** — read it from the system.
- **NEVER write under `${plugin_dir}`** — that's the plugin install location (potentially read-only, gets overwritten on `/plugin marketplace update`). Results and memory always go under `${data_dir}`.
- **NEVER try to spawn `Agent` from inside a subagent prompt.** Subagents cannot spawn further subagents — the `Agent` tool only exists in the main session where this skill runs.
