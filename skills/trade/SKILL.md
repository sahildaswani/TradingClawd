---
name: trade
description: "Run the full TradingClawd multi-agent pipeline on one or more tickers and produce a portfolio decision (Buy / Overweight / Hold / Underweight / Sell) per ticker. Usage: `/trade NVDA` or `/trade NVDA,AAPL,TSLA` or `/trade NVDA 2026-05-22 debate=2 risk=2 analysts=market,news portfolio=book.json language=Spanish`."
argument-hint: "<ticker>[,<ticker>...] [trade-date YYYY-MM-DD] [debate=N] [risk=N] [analysts=...] [portfolio=FILE] [language=...]"
allowed-tools: Bash, Read, Workflow
---

# /trade — multi-agent trading pipeline

Runs the whole pipeline for each ticker as the `tradingclawd:trade-pipeline` workflow: four analysts in parallel → bull/bear debate → research manager → trader → aggressive/conservative/neutral risk debate → portfolio manager. Each ticker runs its own chain, so one ticker never waits for another. The portfolio manager writes `portfolio_decision.json` and records the decision in the memory log itself. Alongside the analysts, a reflector settles past decisions whose holding window has traded, so the portfolio manager can learn from how they turned out.

## Step 1: Prepare the run

Parse `$ARGUMENTS`:
- **tickers**: the first argument, comma-separated (e.g. `NVDA` or `NVDA,AAPL,TSLA`). If none were given, ask which tickers to analyze.
- **trade date**: an optional `YYYY-MM-DD`. Leave it out to use today.
- **rounds**: optional `debate=N` (bull/bear rounds) and `risk=N` (risk-debate rounds), each 1 to 5, default 1.
- **analysts**: optional `analysts=market,news` to run a subset of market, social, news, fundamentals.
- **portfolio**: optional `portfolio=<file.json>` with the user's cash and positions; without it, `<data_dir>/portfolio.json` is used if it exists. The trader, risk analysts and portfolio manager size against it.
- **language**: optional `language=<name>` for the written reports (ratings stay in English).

Then run (include only the flags the user gave):

```bash
RUN="${CLAUDE_PLUGIN_ROOT}/scripts/run.sh"
[ -x "$RUN" ] || RUN=$(ls -d "$HOME"/.claude/plugins/cache/*/tradingclawd/*/scripts/run.sh 2>/dev/null | sort -V | tail -1)
"$RUN" prepare_run.py --tickers "<TICKERS>" --date <DATE> --debate-rounds <N> --risk-rounds <N> --analysts <LIST> --portfolio <FILE> --language <NAME>
```

If `portfolio_file` in the output is set, mention that the decisions will size against it.

It prints the run as JSON. If it exits with an error, show the error to the user and stop. The first run on a machine also builds TradingClawd's Python environment, which takes about a minute.

## Step 2: Start the workflow

Tell the user in one line: the tickers, the trade date, the rounds, `agents_planned`, and that results go to `<data_dir>/results/<TICKER>/<DATE>/`.

Call the **Workflow** tool with `name: "tradingclawd:trade-pipeline"` and `args` set to the JSON object prepare_run printed, passed as an object, not a string. Tell the user they can watch progress with `/workflows`, then end your turn.

## Step 3: When the workflow finishes

The completion notification carries the workflow's result: `trade_date`, `memory_log`, and one entry per ticker in `results`. Print:

| Ticker | Rating | Research plan | Trader | Summary |
|---|---|---|---|---|

using each result's `rating`, `research_recommendation`, `trader_action` and the first sentence of `executive_summary`.

For any ticker whose `status` is `REVIEW`, show its `failure` and how to resume from what is already on disk:
- stopped at `analyze`: `/tradingclawd:trade <TICKER> <DATE>`
- stopped at `debate`: `/tradingclawd:trade-debate <TICKER> <DATE>`
- stopped at `decide`: `/tradingclawd:trade-decide <TICKER> <DATE>`

Then one line on the memory log from the result's `memory`: how many past decisions were settled this run (name them), any that `failed` (with the reason; they stay pending and are retried next run), and how many are `still_pending`. If `reflector_failed` is true, say the lessons could not be written this run.

End with the results path, each ticker's `complete_report.html` (or `.md`) in its results folder, and the decision log path (`memory_log`).

## Rules

- Never write under the plugin directory; results and the memory log live under the data directory prepare_run reports.
- Do not invent the trade date; prepare_run reads it from the system.
