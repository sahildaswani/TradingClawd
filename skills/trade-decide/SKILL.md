---
name: trade-decide
description: "Run the trader + risk debate + portfolio manager phases for one or more tickers. Needs research_plan.json. Usage: `/trade-decide NVDA [2026-05-22] [rounds=1]`."
argument-hint: "<ticker>[,<ticker>...] [trade-date YYYY-MM-DD] [rounds=N]"
allowed-tools: Bash, Read, Workflow
---

# /trade-decide — trader, risk debate and final decision

Picks up where `/trade-debate` left off, through the `tradingclawd:trade-pipeline` workflow: the trader, then the risk debate (aggressive, conservative, neutral in turn, for each round), then the portfolio manager, who writes `portfolio_decision.json` and records it in the memory log. Earlier files from these steps for the same date are moved to `_previous_runs/` first.

## Step 1: Prepare the run

Parse `$ARGUMENTS` as `<tickers> [<YYYY-MM-DD>] [rounds=N]` (rounds 1 to 5, default 1). Then run, leaving out flags that were not given:

```bash
RUN="${CLAUDE_PLUGIN_ROOT}/scripts/run.sh"
[ -x "$RUN" ] || RUN=$(ls -d "$HOME"/.claude/plugins/cache/*/tradingclawd/*/scripts/run.sh 2>/dev/null | sort -V | tail -1)
"$RUN" prepare_run.py --tickers "<TICKERS>" --date <DATE> --start-at decide --risk-rounds <N> --portfolio <FILE> --language <NAME>
```

If it exits with an error (for example a missing `research_plan.json`), show the error, which names the command to run first, and stop.

Optional `portfolio=<file.json>` (else `<data_dir>/portfolio.json` if present) gives the trader, risk analysts and portfolio manager the user's holdings; `language=<name>` sets the language. Leave out flags that were not given.

## Step 2: Start the workflow

Tell the user in one line what is starting. Call the **Workflow** tool with `name: "tradingclawd:trade-pipeline"` and `args` set to the JSON object prepare_run printed (an object, not a string). Mention `/workflows`, then end your turn.

## Step 3: When the workflow finishes

For each ticker print `<TICKER> @ <trade_date>: <rating> — <first sentence of executive_summary>` and the path to its `portfolio_decision.json` and `complete_report.html`. If a ticker's `status` is `REVIEW`, show its `failure`. Then one line on the memory log from the result's `memory`: how many past decisions were settled this run (name them), any that `failed` (with the reason; they stay pending and are retried next run), and how many are `still_pending`. If `reflector_failed` is true, say the lessons could not be written this run.

End with the decision log path (`memory_log`).
