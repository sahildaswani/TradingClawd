---
name: trade-backtest
description: "Backtest TradingClawd over a grid of tickers and past dates: runs the full pipeline for every (ticker, date) cell into its own data folder, then scores each decision against the return that followed. Usage: `/trade-backtest NVDA,AAPL 2026-07-01..2026-09-30 every=14` or `/trade-backtest NVDA 2026-08-03,2026-08-17 analysts=market,news`."
argument-hint: "<ticker>[,<ticker>...] <date,date,... | START..END every=N> [analysts=...] [debate=N] [risk=N]"
allowed-tools: Bash, Read, Workflow, AskUserQuestion
---

# /trade-backtest — decisions over a ticker × date grid

Each cell is an independent past-dated run of the same `tradingclawd:trade-pipeline` workflow: the data scripts serve only what was known on that date (news within the window, statements as filed, profile and live-only sources withheld). Cells don't learn from each other: no past decisions are settled during a backtest. When all cells finish, `backtest_score.py` measures each decision over the holding window that followed (5 trading days; `TRADINGCLAWD_HOLDING_DAYS` changes it).

## Step 1: Prepare the grid

Parse `$ARGUMENTS`:
- **tickers**: the first argument, comma-separated.
- **dates**: either a comma-separated list (`2026-08-03,2026-08-17`) or a range `START..END every=N` (every N calendar days; default every=7). Dates must be in the past; dates within the last ~8 days can run but can't be scored yet.
- optional `analysts=` (subset of market,social,news,fundamentals), `debate=N`, `risk=N`.

Then run, with `--dates <list>` or `--date-range <START>:<END>:<N>`, and only the optional flags given:

```bash
RUN="${CLAUDE_PLUGIN_ROOT}/scripts/run.sh"
[ -x "$RUN" ] || RUN=$(ls -d "$HOME"/.claude/plugins/cache/*/tradingclawd/*/scripts/run.sh 2>/dev/null | sort -V | tail -1)
BT_DIR="${TRADINGCLAWD_DIR:-$(pwd)/.tradingclawd}/backtests/$(date +%Y%m%d-%H%M%S)"
"$RUN" prepare_run.py --tickers "<TICKERS>" --dates <DATES> --data-dir "$BT_DIR" --no-settle --analysts <A> --debate-rounds <N> --risk-rounds <N>
```

If it exits with an error, show it and stop.

## Step 2: Confirm the cost, then start

Tell the user the grid (tickers × dates = cells), `agents_planned`, and the folder. If `agents_planned` is more than 40, ask with AskUserQuestion whether to run it, offering to cut the grid or run with `analysts=market,news` instead; stop if they decline. Workflows run at most about 6 agents at once, so a large grid takes a while.

Call the **Workflow** tool with `name: "tradingclawd:trade-pipeline"` and `args` set to the JSON object prepare_run printed (an object, not a string). Mention `/workflows`, then end your turn.

## Step 3: When the workflow finishes

Score the decisions:

```bash
RUN="${CLAUDE_PLUGIN_ROOT}/scripts/run.sh"
[ -x "$RUN" ] || RUN=$(ls -d "$HOME"/.claude/plugins/cache/*/tradingclawd/*/scripts/run.sh 2>/dev/null | sort -V | tail -1)
"$RUN" backtest_score.py --data-dir "<data_dir from prepare_run>"
```

Show the summary it prints (hit rates, mean signed alpha, the by-rating table), list any cells whose `status` was `REVIEW` with their `failure`, and give the path to `backtest_summary.md` and the per-cell results under `<data_dir>/results/`. Remind the user that a small grid in one market regime says little about skill.
