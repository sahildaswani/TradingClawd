# TradingClawd

A Claude Code plugin that ports the [TradingAgents](https://github.com/tauricresearch/tradingagents) multi-agent trading framework to native Claude Code primitives. Twelve specialized subagents (four analysts, two researchers, a research manager, a trader, three risk debators, a portfolio manager) collaborate through structured debate to produce a trading decision for any ticker.

## What it does

Run `/trade NVDA` (or `/trade NVDA,AAPL,TSLA` for multi-ticker parallel) and the pipeline:

1. **Four analysts run in parallel** — market (technical indicators), social (Reddit + company news sentiment), news (macro context), fundamentals (financial statements).
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

**Python 3.10+** available as `python3`. That's all: the first data call builds TradingClawd's own virtual environment under `~/.cache/tradingclawd/` (about a minute, once) and installs `requirements.txt` into it, so the scripts never touch your global Python packages. Changing `requirements.txt` builds a fresh environment on the next call.

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

### Reddit

Retail sentiment comes from Reddit's public RSS search feed: r/wallstreetbets, r/stocks and r/investing (or r/CryptoCurrency, r/CryptoMarkets and the coin's own subreddit for a crypto pair like `BTC-USD`). No login or API key — Reddit's JSON API rejects anonymous clients, but the RSS feed serves them.

Two limits come with it:

- **About one request per minute per IP.** Each ticker's social analyst makes one request; in a multi-ticker run they queue behind each other (via a lock in `~/.cache/tradingclawd/`), so the Nth ticker waits roughly N−1 minutes for its turn. A ticker that would wait more than 5 minutes reports Reddit as unavailable instead.
- **No vote or comment counts.** The analyst judges posts by their content.

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
├── agents/                             # 12 subagent definitions
│   ├── ta-market-analyst.md            # technical analysis
│   ├── ta-social-analyst.md            # Reddit (RSS) + yfinance company news
│   ├── ta-news-analyst.md              # macro / global news
│   ├── ta-fundamentals-analyst.md      # financials
│   ├── ta-bull-researcher.md
│   ├── ta-bear-researcher.md
│   ├── ta-research-manager.md          # 5-tier recommendation (JSON)
│   ├── ta-trader.md                    # 3-tier action + entry/stop (JSON)
│   ├── ta-risk-aggressive.md
│   ├── ta-risk-conservative.md
│   ├── ta-risk-neutral.md
│   └── ta-portfolio-manager.md         # final decision (JSON)
├── skills/                             # 4 slash commands
│   ├── trade/SKILL.md
│   ├── trade-analyze/SKILL.md
│   ├── trade-debate/SKILL.md
│   └── trade-decide/SKILL.md
├── scripts/                            # data layer (yfinance + stockstats + Reddit RSS CLIs)
│   ├── run.sh                          # runs a script in the plugin's own Python venv
│   ├── _common.py
│   ├── _google_news.py                 # Google News RSS search (shared by both news scripts)
│   ├── get_stock_data.py               # OHLCV
│   ├── get_indicators.py               # MACD, RSI, BBANDS, ATR, VWMA, etc.
│   ├── get_fundamentals.py             # P/E, margins, etc.
│   ├── get_balance_sheet.py
│   ├── get_cashflow.py
│   ├── get_income_statement.py
│   ├── get_news.py                     # ticker-specific news (Google News, then Yahoo)
│   ├── get_global_news.py              # macro news (Google News, then Yahoo)
│   ├── get_reddit.py                   # Reddit posts via public RSS
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

- **Market data** (OHLCV, fundamentals, insider trades): [**yfinance**](https://github.com/ranaroussi/yfinance) — free, no API key.
- **Company and macro news**: Google News RSS search — keyless, searched within the analysis window, so past-dated runs get the news of their own week. Headlines only (no article text). Falls back to Yahoo Finance, which serves only recent items.
- **Technical indicators**: [**stockstats**](https://github.com/jealous/stockstats) computed off the OHLCV pulled from yfinance.
- **Retail social signal**: Reddit's public RSS search feed — no login, about one request per minute (see [Reddit](#reddit)).

No Twitter / X integration (paid API). No Alpha Vantage integration (yfinance already covers the same data without a key).

## Differences from the original TradingAgents

- No LangChain / LangGraph runtime — orchestration is driven by the `/trade` skill itself (Markdown spec executed by Claude in the main session), using wave-based parallelization to fan out subagents per phase. Multi-ticker runs spawn each phase's subagents for every ticker in one parallel batch.
- No multi-provider LLM client. The "LLM" is whichever Claude model is running Claude Code.
- No checkpoint / resume — runs that fail mid-pipeline can be resumed by invoking the relevant `/trade-*` sub-skill (analyst reports / research plan are persisted on disk).
- No backtesting (`backtrader`).
- Only the `yfinance` data vendor (plus Google News and Reddit RSS) is wired up. The interface mirrors the upstream tool signatures, so adding Alpha Vantage scripts in `scripts/` later is straightforward.

## Not financial advice

This is a research / educational tool. Don't trade real money on its output.
