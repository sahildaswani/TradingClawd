# TradingClawd

A Claude Code plugin that ports the [TradingAgents](https://github.com/tauricresearch/tradingagents) multi-agent trading framework to native Claude Code primitives. Twelve specialized subagents (four analysts, two researchers, a research manager, a trader, three risk debators, a portfolio manager) collaborate through structured debate to produce a trading decision for any ticker.

## What it does

Run `/trade NVDA` (or `/trade NVDA,AAPL,TSLA` for multi-ticker parallel) and the pipeline:

1. **Four analysts run in parallel** — market (technical indicators), social (news sentiment), news (macro context), fundamentals (financial statements).
2. **Bull vs Bear research debate** — researchers argue, a Research Manager judges and produces a 5-tier recommendation (`Buy / Overweight / Hold / Underweight / Sell`).
3. **Trader** turns the recommendation into a concrete proposal (`Buy / Hold / Sell` + entry price + stop-loss + sizing).
4. **Aggressive vs Conservative vs Neutral risk debate** — three risk analysts argue about the trader's proposal.
5. **Portfolio Manager** synthesizes everything into a final decision, factoring in prior decisions from the memory log.
6. **Memory log** — every decision is appended to `${data_dir}/memory/trading_memory.md`. On future runs of the same ticker, the Portfolio Manager reads the log and incorporates prior lessons into its thesis.

Per-ticker artifacts (analyst reports, debate turns, JSON outputs) land in `${data_dir}/results/<TICKER>/<DATE>/`.

## Where results are written

TradingClawd writes everything (per-run artifacts and the decision memory log) to a single **data directory**, resolved per invocation:

1. **`$TRADINGCLAWD_DIR`** if you've set that env var (e.g. `export TRADINGCLAWD_DIR=~/tradingclawd-archive`). Use this for a single shared archive across all your projects.
2. **`$(pwd)/.tradingclawd/`** otherwise — a per-project directory in whichever folder you launched Claude Code from. This is the default and is usually what you want: each project (e.g. one folder per trading strategy) gets its own decision history.

Crucially, TradingClawd **never** writes inside the plugin install directory — that's read-only state managed by `/plugin marketplace update` and would be overwritten.

## Install

### Dependencies

**Python 3.10+** — for the bundled data scripts (yfinance, stockstats, pandas). Claude Code plugins don't auto-install Python dependencies, so install them yourself:

```bash
pip install yfinance stockstats pandas python-dateutil requests
```

(Equivalent to `pip install -r requirements.txt` from the cloned repo.)

**Node.js / npm 18+** — for the Reddit MCP server (auto-fetched via `npx` on first use). Confirm with `node --version` and `npx --version`.

### As a Claude Code plugin

In any Claude Code session, run:

```
/plugin marketplace add sahildaswani/TradingClawd
/plugin install tradingclawd@tradingclawd-marketplace
```

Verify it's loaded:

```
/plugin list
```

Skills will appear namespaced as `/tradingclawd:trade`, `/tradingclawd:trade-analyze`, `/tradingclawd:trade-debate`, `/tradingclawd:trade-decide`.

To pull updates after the repo changes:

```
/plugin marketplace update tradingclawd-marketplace
```

### Optional: Reddit auth (for higher rate limits + richer social signal)

The social analyst pulls retail sentiment from r/wallstreetbets, r/stocks, and r/investing via the bundled [reddit-mcp-server](https://github.com/jordanburke/reddit-mcp-server). **By default it runs in anonymous mode** (~10 requests/minute, no setup) and pulls a conservative 3 calls per analysis. That's fine for single-ticker runs.

If you run **multi-ticker** commands frequently (`/trade NVDA,AAPL,TSLA,...`) or want richer Reddit context (top posts from 3 subs, more comment threading, ~8 calls per analysis), upgrade to authenticated mode. Authenticated mode raises the limit to 60–100 req/min AND the social analyst automatically expands its Reddit call budget when it detects credentials.

**One-time setup:**

1. Sign in to Reddit and go to https://www.reddit.com/prefs/apps
2. Click "create another app..." at the bottom
3. Fill in:
   - **name**: anything (e.g. `tradingclawd-mcp`)
   - **type**: select **`script`** (no OAuth, no user redirect — this is the simplest type)
   - **redirect uri**: `http://localhost:8080` (required field but never used by `script` apps)
4. Click "create app". Reddit shows two strings:
   - The client ID is the random string directly under the app name
   - The client secret is the value labelled `secret`
5. Add to your shell rc (`~/.zshrc`, `~/.bashrc`):
   ```bash
   export REDDIT_CLIENT_ID="<the ID from step 4>"
   export REDDIT_CLIENT_SECRET="<the secret from step 4>"
   export REDDIT_AUTH_MODE="authenticated"  # optional — forces it on
   ```
6. `source ~/.zshrc` (or restart your terminal) and re-launch Claude Code.

The MCP server inherits these env vars from Claude Code's process. The plugin manifest never sees the credentials — they live only in your shell, never in version control.

## Commands

| Command | What it does |
|---|---|
| `/trade <tickers> [date]` | Full pipeline. Comma-separated tickers run in parallel. |
| `/trade-analyze <ticker> [date]` | Only the four analyst subagents — produces the four report files and stops. |
| `/trade-debate <ticker> [date] [rounds=N]` | Bull/bear debate + Research Manager. Requires analyst reports to already exist. |
| `/trade-decide <ticker> [date] [rounds=N]` | Trader + risk debate + Portfolio Manager. Requires research plan to already exist. |

`[date]` defaults to today (system date). `[rounds=N]` defaults to 1.

## Layout

```
TradingClawd/
├── .claude-plugin/plugin.json          # plugin manifest
├── agents/                             # 13 subagent definitions
│   ├── ta-market-analyst.md            # technical analysis
│   ├── ta-social-analyst.md            # news sentiment
│   ├── ta-news-analyst.md              # macro / global news
│   ├── ta-fundamentals-analyst.md      # financials
│   ├── ta-bull-researcher.md
│   ├── ta-bear-researcher.md
│   ├── ta-research-manager.md          # 5-tier recommendation (JSON)
│   ├── ta-trader.md                    # 3-tier action + entry/stop (JSON)
│   ├── ta-risk-aggressive.md
│   ├── ta-risk-conservative.md
│   ├── ta-risk-neutral.md
│   ├── ta-portfolio-manager.md         # final decision (JSON)
│   └── ta-ticker-orchestrator.md       # drives the full pipeline per ticker
├── skills/                             # 4 slash commands
│   ├── trade/SKILL.md
│   ├── trade-analyze/SKILL.md
│   ├── trade-debate/SKILL.md
│   └── trade-decide/SKILL.md
├── scripts/                            # data layer (yfinance + stockstats CLIs)
│   ├── _common.py
│   ├── get_stock_data.py               # OHLCV
│   ├── get_indicators.py               # MACD, RSI, BBANDS, ATR, VWMA, etc.
│   ├── get_fundamentals.py             # P/E, margins, etc.
│   ├── get_balance_sheet.py
│   ├── get_cashflow.py
│   ├── get_income_statement.py
│   ├── get_news.py                     # ticker-specific news
│   ├── get_global_news.py              # macro news
│   └── get_insider_transactions.py
└── requirements.txt                    # Python deps for the data scripts
```

User-visible data (written to `$TRADINGCLAWD_DIR` or `$(pwd)/.tradingclawd/`, NOT inside the plugin):

```
<data_dir>/
├── memory/trading_memory.md            # append-only decision log (created at runtime)
└── results/<TICKER>/<DATE>/            # per-run artifacts (created at runtime)
    ├── market_report.md
    ├── sentiment_report.md
    ├── news_report.md
    ├── fundamentals_report.md
    ├── debate_turns/{bull_1.md, bear_1.md, ...}
    ├── research_plan.json
    ├── trader_proposal.json
    ├── risk_turns/{aggressive_1.md, conservative_1.md, neutral_1.md, ...}
    └── portfolio_decision.json
```

## Data sources

- **Market data** (OHLCV, fundamentals, company news): [**yfinance**](https://github.com/ranaroussi/yfinance) — free, no API key.
- **Technical indicators**: [**stockstats**](https://github.com/jealous/stockstats) computed off the OHLCV pulled from yfinance.
- **Retail social signal**: [**reddit-mcp-server**](https://github.com/jordanburke/reddit-mcp-server) — bundled via the plugin's MCP config. Anonymous mode by default (no API key, ~10 req/min). Optional authenticated mode lifts the rate limit to 60–100 req/min and expands the social analyst's call budget for richer multi-sub coverage — see [Optional: Reddit auth](#optional-reddit-auth-for-higher-rate-limits--richer-social-signal) above.

No Twitter / X integration (paid API). No Alpha Vantage integration (yfinance already covers the same data without a key).

## Differences from the original TradingAgents

- No LangChain / LangGraph runtime — orchestration is done by the `ta-ticker-orchestrator` subagent reading a Markdown spec.
- No multi-provider LLM client. The "LLM" is whichever Claude model is running Claude Code.
- No checkpoint / resume — runs that fail mid-pipeline can be resumed by invoking the relevant `/trade-*` sub-skill (analyst reports / research plan are persisted on disk).
- No backtesting (`backtrader`).
- Only the `yfinance` data vendor is wired up. The interface mirrors the upstream tool signatures, so adding Alpha Vantage scripts in `scripts/` later is straightforward.

## Not financial advice

This is a research / educational tool. Don't trade real money on its output.
