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

## Wave 0.5: Pre-fetch Reddit signal (main session only — subagents cannot access plugin MCP tools)

**Why this lives here, not in the social analyst:** Plugin-bundled MCP tools (like `mcp__plugin_tradingclawd_reddit__*`) are only available to skills running in the main session. Subagents spawned via `Agent` cannot access them, regardless of what's declared in their `tools:` frontmatter. So the skill itself must do the Reddit fetching and persist the results to disk; the social analyst then reads from disk.

### Detect auth mode and choose budget

```bash
if [ -n "${REDDIT_CLIENT_ID:-}" ] && [ -n "${REDDIT_CLIENT_SECRET:-}" ]; then
  REDDIT_AUTH="AUTHENTICATED"   # ~60-100 req/min — use the wider budget
else
  REDDIT_AUTH="ANONYMOUS"       # ~10 req/min — keep it tight
fi
echo "Reddit auth mode: ${REDDIT_AUTH}"
```

### Round A: search + top_posts (parallel for ALL tickers)

In a single message, batch these MCP calls (the exact mix depends on `REDDIT_AUTH`):

**ANONYMOUS mode — 2 calls per ticker:**
- `mcp__plugin_tradingclawd_reddit__search_reddit` with `{query: "<TICKER>", time_filter: "week", limit: 10}`
- `mcp__plugin_tradingclawd_reddit__get_top_posts` with `{subreddit: "wallstreetbets", time_filter: "week", limit: 10}`

**AUTHENTICATED mode — 5 calls per ticker:**
- `mcp__plugin_tradingclawd_reddit__search_reddit` with `{query: "<TICKER>", time_filter: "week", limit: 10}`
- `mcp__plugin_tradingclawd_reddit__search_reddit` with `{query: "<company-name-if-known>", time_filter: "week", limit: 10}` (skip if you don't have the company name handy from the ticker)
- `mcp__plugin_tradingclawd_reddit__get_top_posts` with `{subreddit: "wallstreetbets", time_filter: "week", limit: 10}`
- `mcp__plugin_tradingclawd_reddit__get_top_posts` with `{subreddit: "stocks", time_filter: "week", limit: 10}`
- `mcp__plugin_tradingclawd_reddit__get_top_posts` with `{subreddit: "investing", time_filter: "week", limit: 10}`

For N tickers, this is N × (2 or 5) calls in ONE message. All in parallel.

### Round B: comments on the most engaged ticker-relevant post (parallel)

From Round A's results, for each ticker identify the single most engaged post that actually mentions the ticker (score × comment count is a good rough heuristic; skip posts that don't reference the ticker even tangentially). If no relevant post exists, skip Round B for that ticker.

In a single message, batch one `mcp__plugin_tradingclawd_reddit__get_post_comments` call per ticker that has a relevant post.

### Round C: write `reddit_signal.md` per ticker

For each ticker, write `${results_dir}/reddit_signal.md` with the auth mode banner at the top and the raw Round A + Round B results, structured like:

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

If a Reddit call errors out (rate limit, network), note it in the file with `**ERROR:** <message>` instead of the data — DON'T abort the pipeline, the analyst can still write a degraded report.

## Wave 1: Analyst phase (parallel across tickers × analyst types)

**In a single message**, spawn `N × 4` subagents — one of each analyst type per ticker. For N tickers this is up to 4N parallel `Agent` calls in one tool-use batch.

Subagent types to use (the `tradingclawd:` prefix is required):

- `tradingclawd:ta-market-analyst`
- `tradingclawd:ta-social-analyst`
- `tradingclawd:ta-news-analyst`
- `tradingclawd:ta-fundamentals-analyst`

Each subagent prompt should include `ticker`, `trade_date`, `results_dir`, `plugin_dir` for that specific ticker.

Wait for all of them to finish. Verify each ticker's `results_dir(T)/` now has `market_report.md`, `sentiment_report.md`, `news_report.md`, `fundamentals_report.md`.

## Wave 2: Research debate (round 1 parallel; rounds 2+ sequential)

**Wave 2.1 — Opening case (round 1, bull AND bear in parallel):**

In one message, spawn BOTH `tradingclawd:ta-bull-researcher` AND `tradingclawd:ta-bear-researcher` for every ticker — that's `N × 2` parallel `Agent` calls. Each gets `{ticker, results_dir, round=1, debate_history=""}` (history is empty because nobody has gone first).

Round 1 is each side's opening statement based on the analyst reports alone. The agents are explicitly told to handle the empty-history case by presenting their case standalone and anticipating likely counterarguments.

**Rounds 2..max_debate_rounds — sequential within ticker (only if `max_debate_rounds > 1`):**

For `n` in 2..`max_debate_rounds`:

- **Wave 2.n.a — Bull rebuttal:** For each ticker, build `debate_history` (concatenated contents of all prior turn files in `results_dir(T)/debate_turns/`, lexical order). In one message, spawn `tradingclawd:ta-bull-researcher` for every ticker in parallel with `{ticker, results_dir, round=n, debate_history}`.
- **Wave 2.n.b — Bear rebuttal:** Rebuild each ticker's history (now includes `bull_<n>.md`). Spawn `tradingclawd:ta-bear-researcher` for every ticker in parallel.

After all rounds finish, move on to Wave 3.

## Wave 3: Research Manager (parallel across tickers)

In one message, spawn `tradingclawd:ta-research-manager` for every ticker in parallel. Each gets `{ticker, trade_date, results_dir}`. Each writes `research_plan.json` into its ticker's `results_dir`.

## Wave 4: Trader (parallel across tickers)

In one message, spawn `tradingclawd:ta-trader` for every ticker in parallel. Each gets `{ticker, trade_date, results_dir}`. Each writes `trader_proposal.json`.

## Wave 5: Risk debate (round 1 parallel; rounds 2+ sequential)

**Wave 5.1 — Opening positions (round 1, all three sides in parallel):**

In one message, spawn ALL THREE of `tradingclawd:ta-risk-aggressive`, `tradingclawd:ta-risk-conservative`, AND `tradingclawd:ta-risk-neutral` for every ticker — that's `N × 3` parallel `Agent` calls. Each gets `{ticker, results_dir, round=1, risk_history=""}`.

Each risk analyst's prompt already includes the "if there are no responses from the other viewpoints yet, present your own argument" clause, so they handle the empty-history case correctly: each writes its own opening position based on the trader's proposal + analyst reports.

**Rounds 2..max_risk_discuss_rounds — sequential triads (only if `max_risk_discuss_rounds > 1`):**

For `n` in 2..`max_risk_discuss_rounds`:

- **Wave 5.n.a — Aggressive rebuttal:** Rebuild each ticker's `risk_history`. Spawn `tradingclawd:ta-risk-aggressive` for every ticker in parallel (one message).
- **Wave 5.n.b — Conservative rebuttal:** Rebuild histories. Spawn `tradingclawd:ta-risk-conservative` for every ticker in parallel.
- **Wave 5.n.c — Neutral rebuttal:** Rebuild histories. Spawn `tradingclawd:ta-risk-neutral` for every ticker in parallel.

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
