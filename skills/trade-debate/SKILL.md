---
name: trade-debate
description: "Run only the bull/bear research debate + research manager for one or more tickers. Needs the analyst reports in ${data_dir}/results/<TICKER>/<DATE>/. Usage: `/trade-debate NVDA [2026-05-22] [rounds=1]`."
argument-hint: "<ticker>[,<ticker>...] [trade-date YYYY-MM-DD] [rounds=N]"
allowed-tools: Bash, Read, Workflow
---

# /trade-debate — research debate only

Runs the bull/bear debate (bull opens, bear answers, for each round) and the research manager through the `tradingclawd:trade-pipeline` workflow, producing `research_plan.json`. Needs the four analyst reports on disk. Earlier debate files for the same date are moved to `_previous_runs/` first.

## Step 1: Prepare the run

Parse `$ARGUMENTS` as `<tickers> [<YYYY-MM-DD>] [rounds=N]` (rounds 1 to 5, default 1). Then run, leaving out flags that were not given:

```bash
RUN="${CLAUDE_PLUGIN_ROOT}/scripts/run.sh"
[ -x "$RUN" ] || RUN=$(ls -d "$HOME"/.claude/plugins/cache/*/tradingclawd/*/scripts/run.sh 2>/dev/null | sort -V | tail -1)
"$RUN" prepare_run.py --tickers "<TICKERS>" --date <DATE> --start-at debate --stop-after debate --debate-rounds <N> --language <NAME>
```

If it exits with an error (for example missing analyst reports), show the error, which names the command to run first, and stop. If the user relies on `TRADINGCLAWD_DIR`, remind them it must be set as it was for the analyst run.

Optional `language=<name>` sets the language of the debate and plan (ratings stay in English). Leave out flags that were not given.

## Step 2: Start the workflow

Tell the user in one line what is starting. Call the **Workflow** tool with `name: "tradingclawd:trade-pipeline"` and `args` set to the JSON object prepare_run printed (an object, not a string). Mention `/workflows`, then end your turn.

## Step 3: When the workflow finishes

For each ticker print the research manager's `research_recommendation`, and read the first ~30 words of `rationale` from `<results_dir>/research_plan.json`. If a ticker's `status` is `REVIEW`, show its `failure`. The next step is `/tradingclawd:trade-decide <TICKER> <DATE>`.
