---
name: trade-debate
description: "Run only the bull/bear research debate + research manager for one ticker. Assumes analyst reports already exist in results/<TICKER>/<DATE>/. Usage: `/trade-debate NVDA [2026-05-22] [rounds=1]`."
argument-hint: "<ticker> [trade-date YYYY-MM-DD] [rounds=N]"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent
---

# /trade-debate — research debate only

Runs the bull/bear debate (configurable rounds) for ONE ticker, then has the research manager produce `research_plan.json`. Requires the four analyst reports to already exist on disk.

## Arguments

Parse `$ARGUMENTS` as: `<ticker> [<YYYY-MM-DD>] [rounds=N]`. Default `trade_date` to today, default `rounds=1`.

## Steps

1. Resolve `plugin_dir` and compute `results_dir`.
2. **Verify the four analyst reports exist** in `${results_dir}/`. If any are missing, stop and tell the user to run `/trade-analyze <ticker> [date]` first.
3. `mkdir -p ${results_dir}/debate_turns`.
4. **Debate loop** for `n` in 1..rounds:
   a. Spawn `ta-bull-researcher` (subagent_type) with `{ticker, results_dir, round=n, debate_history}`. The `debate_history` is the concatenation of every previously-written file in `${results_dir}/debate_turns/` in order — include its actual contents in the prompt, not just file paths.
   b. After bull_<n>.md exists, spawn `ta-bear-researcher` with the updated history.
5. After the loop, spawn `ta-research-manager` with `{ticker, trade_date, results_dir}`. It writes `research_plan.json`.
6. Read `research_plan.json` and print a 2-line summary: the `recommendation` and the first ~30 words of `rationale`.

Tell the user the next step is `/trade-decide <ticker> [date]` to run the trader + risk debate + portfolio manager.
