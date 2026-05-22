---
name: trade-analyze
description: "Run only the analyst phase of the TradingClawd pipeline (market + social + news + fundamentals) for one ticker. Writes four reports to ${data_dir}/results/<TICKER>/<DATE>/. Useful for refreshing data without re-running debates. Usage: `/trade-analyze NVDA [2026-05-22]`."
argument-hint: "<ticker> [trade-date YYYY-MM-DD]"
allowed-tools: Bash, Read, Write, Glob, Grep, Agent
---

# /trade-analyze — analyst phase only

Runs the four analyst subagents in parallel for ONE ticker and stops. No research debate, no trader, no risk debate, no final decision.

## Arguments

Parse `$ARGUMENTS` as: `<ticker> [<YYYY-MM-DD>]`. Default `trade_date` to today (via `date +%Y-%m-%d`). If no ticker provided, ask.

## Steps

### 1. Resolve `plugin_dir` and `data_dir`

```bash
# plugin_dir — where the bundled Python data scripts live.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -f "${CLAUDE_PLUGIN_ROOT}/scripts/_common.py" ]; then
  PLUGIN_DIR="${CLAUDE_PLUGIN_ROOT}"
else
  # Fall back to probing the user's plugin cache.
  PLUGIN_DIR=$(find "$HOME/.claude/plugins" -type f -name "_common.py" -path "*/tradingclawd/scripts/*" 2>/dev/null | head -1 | sed 's|/scripts/_common.py||')
fi

# data_dir — env-var override or default to $(pwd)/.tradingclawd
if [ -n "${TRADINGCLAWD_DIR:-}" ]; then
  DATA_DIR="${TRADINGCLAWD_DIR}"
else
  DATA_DIR="$(pwd)/.tradingclawd"
fi
mkdir -p "${DATA_DIR}"
```

### 2. Compute `results_dir` and create it

```
results_dir = ${data_dir}/results/<TICKER>/<TRADE_DATE>
mkdir -p ${results_dir}
```

### 2.5. Pre-fetch Reddit signal (main session only — subagents cannot access plugin MCP tools)

**Why this lives here, not in the social analyst:** Plugin-bundled MCP tools are only available to skills running in the main session. The social analyst subagent cannot call `mcp__plugin_tradingclawd_reddit__*` — so the skill itself must fetch and persist the Reddit data, and the analyst reads from disk.

**Detect auth mode:**
```bash
if [ -n "${REDDIT_CLIENT_ID:-}" ] && [ -n "${REDDIT_CLIENT_SECRET:-}" ]; then
  REDDIT_AUTH="AUTHENTICATED"
else
  REDDIT_AUTH="ANONYMOUS"
fi
```

**Round A — batched MCP calls in one message:**

- **ANONYMOUS (2 calls):**
  - `mcp__plugin_tradingclawd_reddit__search_reddit` `{query: "<TICKER>", time_filter: "week", limit: 10}`
  - `mcp__plugin_tradingclawd_reddit__get_top_posts` `{subreddit: "wallstreetbets", time_filter: "week", limit: 10}`
- **AUTHENTICATED (5 calls):**
  - `search_reddit` for ticker AND for company name (2 calls)
  - `get_top_posts` from `wallstreetbets`, `stocks`, `investing` (3 calls)

**Round B — comments on most engaged ticker-relevant post (1 call):**

From Round A's results, pick the single post that most strongly mentions the ticker AND has the highest engagement (score × comments is a fine heuristic). Then call:
- `mcp__plugin_tradingclawd_reddit__get_post_comments` `{post_id: "<id>"}`

If no relevant post exists, skip Round B.

**Round C — write `${results_dir}/reddit_signal.md`:**

```markdown
# Reddit signal for <TICKER> @ <trade_date>
**Auth mode:** <ANONYMOUS|AUTHENTICATED>
**Subreddits sampled:** <list>

## search_reddit("<TICKER>", week) — N results
<post titles, scores, authors, subreddits, comment counts, links>

## get_top_posts(<sub>, week) — N results
<same shape>

## Comments on most engaged post (<title>)
<top 5-10 comments with author + score + body>
```

If a Reddit call errors (rate limit, network), record `**ERROR:** <message>` in the file instead of aborting — the social analyst will still write a degraded report.

### 3. Spawn four analyst subagents IN PARALLEL

**In a single message**, spawn the four analyst subagents in parallel (use these exact `subagent_type` values — the `tradingclawd:` prefix is required):
   - `tradingclawd:ta-market-analyst`
   - `tradingclawd:ta-social-analyst`
   - `tradingclawd:ta-news-analyst`
   - `tradingclawd:ta-fundamentals-analyst`

Each prompt should include `ticker`, `trade_date`, `results_dir`, `plugin_dir`.

### 4. Confirm

When all four return, confirm the four report files exist and print a one-line summary per analyst (e.g. "market_report.md: 4.3 KB"). Tell the user the next step is `/trade-debate <ticker> [date]` to run the bull/bear research debate.

## Rules

- NEVER write under `${plugin_dir}` — results always go under `${data_dir}`.
