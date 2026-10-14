# TradingClawd

A Claude Code plugin that ports the [TradingAgents](https://github.com/tauricresearch/tradingagents) multi-agent trading framework to native Claude Code primitives. Thirteen specialized subagents (four analysts, two researchers, a research manager, a trader, three risk debators, a portfolio manager, and a reflector that learns from past outcomes) collaborate through structured debate to produce a trading decision for any ticker.

## What it does

Run `/trade NVDA` (or `/trade NVDA,AAPL,TSLA` for several tickers) and, for each ticker, the pipeline:

1. **Four analysts run in parallel** — market (technical indicators, checked against a verified price snapshot), social (Reddit + company news; opens with a sentiment band, 0–10 score and confidence), news (macro context), fundamentals (financial statements; stocks only).
2. **Bull vs Bear research debate** — the bull opens, the bear answers it, for each round; a Research Manager judges and produces a 5-tier recommendation (`Buy / Overweight / Hold / Underweight / Sell`).
3. **Trader** turns the recommendation into a concrete proposal (`Buy / Hold / Sell` + entry price + stop-loss + sizing).
4. **Aggressive vs Conservative vs Neutral risk debate** — three risk analysts take turns arguing about the trader's proposal, each answering the ones before.
5. **Portfolio Manager** synthesizes everything into a final decision, factoring in prior decisions from the memory log.
6. **Memory log** — every decision is recorded in `${data_dir}/memory/trading_memory.md` as pending. Once its holding window has traded (5 trading days; set `TRADINGCLAWD_HOLDING_DAYS` to change it), the next run that reaches a decision settles it: the return and the alpha against a benchmark are computed from prices (SPY for US tickers, the local index for `.T`, `.HK`, `.L`, `.NS` and other exchange suffixes), and a reflector agent, running alongside the analysts, writes a 2–4 sentence lesson. The Portfolio Manager reads this ticker's last five settled decisions and three lessons from other tickers, only those whose outcome was known by the trade date, so a past-dated run never learns from the future. Logs written before 0.7.0 are converted automatically, and the original is kept beside them.

Per-ticker artifacts (analyst reports, debate turns, JSON outputs) land in `${data_dir}/results/<TICKER>/<DATE>/`.

### Tickers and instruments

Give tickers as Yahoo Finance writes them (`NVDA`, `7203.T`, `0700.HK`, `BTC-USD`) or as brokers do: `XAUUSD` becomes gold futures `GC=F`, `BTCUSDT` becomes `BTC-USD`, `EURUSD` becomes `EURUSD=X`, `US500` becomes `^GSPC`, `700.HK` becomes `0700.HK`, `600519.SH` becomes `600519.SS`. Each instrument's name, sector, exchange and quote currency are resolved once per run and given to every agent, so none of them drifts to a different company. A past-dated run gets only the name, since today's sector or exchange may not have applied then. Crypto, currency pairs, futures and indices skip the fundamentals analyst, as they have no company financials.

### How a run works

`/trade` is a thin launcher. It runs `scripts/prepare_run.py` (paths, date, tickers, results folders, prerequisite checks), then starts the plugin's bundled **Claude Code workflow**, `tradingclawd:trade-pipeline`, which runs every agent. Each ticker runs its own chain, so a fast ticker moves on to its debate while a slow one is still in its analysts. The Research Manager, Trader and Portfolio Manager return schema-checked JSON, so an invalid rating can't slip through; a ticker whose step fails is marked `REVIEW` and the others carry on. Watch a run with `/workflows`.

**Requirements:** Claude Code with workflows enabled. They're on by default on Max, Team, Enterprise and API plans; on **Pro**, turn on *Dynamic workflows* in `/config`. The first run may ask permission to start the workflow; add the allow rule `Workflow(tradingclawd:trade-pipeline)` to skip that. Run TradingClawd from an interactive session and keep it open while a run is going: closing Claude Code stops the workflow (re-run with the matching `/trade-*` command to pick up from what's on disk). A single ticker at one round is 12 agents and counts toward your plan's usage like any other subagents.

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
| `/trade <tickers> [date] [debate=N] [risk=N] [analysts=…] [portfolio=FILE] [language=…]` | Full pipeline. Comma-separated tickers each run their own chain. |
| `/trade-analyze <tickers> [date] [analysts=…]` | Only the analysts — produces their report files and stops. |
| `/trade-debate <tickers> [date] [rounds=N]` | Bull/bear debate + Research Manager. Requires the analyst reports. |
| `/trade-decide <tickers> [date] [rounds=N] [portfolio=FILE]` | Trader + risk debate + Portfolio Manager. Requires the research plan. |
| `/trade-backtest <tickers> <dates or START..END every=N>` | Runs every (ticker, date) cell as a past-dated run in its own folder, then scores each decision against the return that followed. |

- `analysts=market,news` runs a subset of market, social, news, fundamentals.
- `portfolio=book.json` gives the trader, risk analysts and Portfolio Manager your holdings to size against (a `portfolio.json` in the data folder is used automatically). Without one they're told not to assume an empty book:
  ```json
  {"cash": 25000, "currency": "USD", "positions": [{"ticker": "NVDA", "quantity": 120, "average_price": 180.5}]}
  ```
- `language=Spanish` writes the reports in another language; ratings and JSON fields stay in English.
- Every decision run writes `complete_report.md` and a self-contained `complete_report.html` (sections listed beside the text; reads well on a phone and in print) in the ticker's results folder.
- A backtest grid costs ~12 agents per cell (fewer with `analysts=`), and `/trade-backtest` asks before starting anything over 40. Cells are independent: no past decisions are settled during a backtest.

`[date]` defaults to today (system date). Rounds default to 1 (max 5). Re-running a stage moves that stage's earlier outputs for the same date, and those of every later stage, into `_previous_runs/`.

## Layout

```
TradingClawd/
├── .claude-plugin/plugin.json          # plugin manifest
├── agents/                             # 13 subagent definitions
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
│   ├── ta-portfolio-manager.md         # final decision (JSON)
│   └── ta-reflector.md                 # lessons from settled past decisions
├── workflows/
│   └── trade-pipeline.js               # the pipeline every /trade-* command runs
├── skills/                             # 5 slash commands (thin launchers)
│   ├── trade/SKILL.md
│   ├── trade-analyze/SKILL.md
│   ├── trade-debate/SKILL.md
│   ├── trade-decide/SKILL.md
│   └── trade-backtest/SKILL.md
├── scripts/                            # data layer (yfinance + stockstats + Reddit RSS CLIs)
│   ├── run.sh                          # runs a script in the plugin's own Python venv
│   ├── prepare_run.py                  # resolves paths/date/tickers, checks prerequisites
│   ├── symbols.py                      # broker/user symbols -> Yahoo symbols, asset type
│   ├── identity.py                     # name/sector/exchange/currency for every agent
│   ├── memory_log.py                   # decision log: store, settle, reflect, past context
│   ├── _common.py
│   ├── _google_news.py                 # Google News RSS search (shared by both news scripts)
│   ├── get_stock_data.py               # OHLCV
│   ├── get_market_snapshot.py          # verified latest OHLCV + indicators (source of truth for numbers)
│   ├── get_indicators.py               # MACD, RSI, BBANDS, ATR, VWMA, etc.
│   ├── get_fundamentals.py             # P/E, margins, etc.
│   ├── get_balance_sheet.py
│   ├── get_cashflow.py
│   ├── get_income_statement.py
│   ├── get_news.py                     # ticker-specific news (Google News, then Yahoo)
│   ├── get_global_news.py              # macro news (Google News, then Yahoo)
│   ├── get_reddit.py                   # Reddit posts via public RSS
│   ├── get_sec_statements.py           # SEC EDGAR statements as filed
│   ├── get_macro.py                    # FRED macro indicators
│   ├── get_prediction_markets.py       # Polymarket odds
│   ├── build_report.py                 # complete_report.md / .html
│   ├── backtest_score.py               # scores a backtest's decisions
│   └── get_insider_transactions.py
└── requirements.txt                    # Python deps for the data scripts
```

User-visible data (written to `$TRADINGCLAWD_DIR` or `$(pwd)/.tradingclawd/`, NOT inside the plugin):

```
<data_dir>/
├── memory/
│   ├── trading_memory.md               # decisions, outcomes and lessons (created at runtime)
│   └── reflections/                    # each lesson as written by the reflector
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

All keyless.

| Source | Used for | On a past-dated run |
|---|---|---|
| [yfinance](https://github.com/ranaroussi/yfinance) | prices, indicators (via [stockstats](https://github.com/jealous/stockstats)), the verified snapshot, company profile, statements, insider trades | prices and indicators up to the date; today's profile and Yahoo's statements are **withheld** (no filing dates); insider trades only if public by then (Form 4 lag) |
| [SEC EDGAR](https://www.sec.gov/edgar) | US financial statements **as filed** | exactly what was on file by the date, restatements only from their filing day. Set `SEC_EDGAR_USER_AGENT="Your Name you@example.com"` to identify yourself to SEC |
| Google News RSS | company and macro headlines (no article text) | the news of that week |
| Reddit RSS | retail discussion (no vote counts) | unavailable: the feed only serves the past week |
| [FRED](https://fred.stlouisfed.org) | policy rate, yields, CPI/PCE, jobs, claims, VIX… | observations count only after a publication lag; values are the latest revision |
| [Polymarket](https://polymarket.com) | market-implied odds of events (Fed moves, recession…) | withheld: only live odds exist |

Not included: Twitter/X (paid API), StockTwits (behind a Cloudflare browser check), Alpha Vantage (yfinance covers the same data without a key).

## Differences from the original TradingAgents

- No LangChain / LangGraph runtime — orchestration is a Claude Code workflow (`workflows/trade-pipeline.js`) whose run order is code: each ticker's chain runs independently, and the debates take turns as upstream's do.
- No multi-provider LLM client. The "LLM" is whichever Claude model is running Claude Code.
- No checkpoint / resume — a run that stops mid-pipeline is resumed by the matching `/trade-*` command, which starts from the reports and plan already on disk.
- Backtesting evaluates decisions (hit rates, alpha by rating), as upstream's does; it is not a portfolio simulator.
- Data comes from keyless sources only (see [Data sources](#data-sources)); no Alpha Vantage, StockTwits or Twitter/X.

## Not financial advice

This is a research / educational tool. Don't trade real money on its output.
