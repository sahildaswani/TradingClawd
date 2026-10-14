---
name: trade-analyze
description: "Run only the analyst phase of the TradingClawd pipeline (market + social + news + fundamentals) for one or more tickers. Writes four reports to ${data_dir}/results/<TICKER>/<DATE>/. Useful for refreshing data without re-running debates. Usage: `/trade-analyze NVDA [2026-05-22]`."
argument-hint: "<ticker>[,<ticker>...] [trade-date YYYY-MM-DD]"
allowed-tools: Bash, Read, Workflow
---

# /trade-analyze — analyst phase only

Runs the four analysts in parallel for each ticker through the `tradingclawd:trade-pipeline` workflow, and stops. No debate, trader, risk debate or final decision.

## Step 1: Prepare the run

Parse `$ARGUMENTS` as `<tickers> [<YYYY-MM-DD>]` (tickers comma-separated; ask if none were given). Then run, leaving `--date` out if no date was given:

```bash
RUN="${CLAUDE_PLUGIN_ROOT}/scripts/run.sh"
[ -x "$RUN" ] || RUN=$(ls -d "$HOME"/.claude/plugins/cache/*/tradingclawd/*/scripts/run.sh 2>/dev/null | sort -V | tail -1)
"$RUN" prepare_run.py --tickers "<TICKERS>" --date <DATE> --stop-after analyze
```

If it exits with an error, show the error and stop. The first run on a machine also builds TradingClawd's Python environment (about a minute).

## Step 2: Start the workflow

Tell the user in one line what is starting (tickers, date, `agents_planned`). Call the **Workflow** tool with `name: "tradingclawd:trade-pipeline"` and `args` set to the JSON object prepare_run printed (an object, not a string). Mention `/workflows` for progress, then end your turn.

## Step 3: When the workflow finishes

For each ticker, list the four reports in its `results_dir` with their sizes, and name any in `missing_reports`. If a ticker's `status` is `REVIEW`, show its `failure`. The next step is `/tradingclawd:trade-debate <TICKER> <DATE>`.
