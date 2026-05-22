# TradingClawd

A Claude Code plugin that ports the [TradingAgents](https://github.com/.../TradingAgents) multi-agent trading framework to native Claude Code primitives. Twelve specialized subagents (four analysts, two researchers, a research manager, a trader, three risk debators, a portfolio manager) collaborate through structured debate to produce a trading decision for any ticker.

## What it does

Run `/trade NVDA` (or `/trade NVDA,AAPL,TSLA` for multi-ticker parallel) and the pipeline:

1. **Four analysts run in parallel** — market (technical indicators), social (news sentiment), news (macro context), fundamentals (financial statements).
2. **Bull vs Bear research debate** — researchers argue, a Research Manager judges and produces a 5-tier recommendation (`Buy / Overweight / Hold / Underweight / Sell`).
3. **Trader** turns the recommendation into a concrete proposal (`Buy / Hold / Sell` + entry price + stop-loss + sizing).
4. **Aggressive vs Conservative vs Neutral risk debate** — three risk analysts argue about the trader's proposal.
5. **Portfolio Manager** synthesizes everything into a final decision, factoring in prior decisions from the memory log.
6. **Memory log** — every decision is appended to `memory/trading_memory.md`. On future runs of the same ticker, the Portfolio Manager reads the log and incorporates prior lessons into its thesis.

Per-ticker artifacts (analyst reports, debate turns, JSON outputs) land in `results/<TICKER>/<DATE>/`.

## Install

### Dependencies

```bash
cd /Users/sahildaswani/Desktop/TradingClawd
pip install -r requirements.txt
```

### As a Claude Code plugin

The plugin directory is `/Users/sahildaswani/Desktop/TradingClawd`. To make Claude Code discover it, either:

- Symlink it into your plugins folder: `ln -s /Users/sahildaswani/Desktop/TradingClawd ~/.claude/plugins/tradingclawd`
- Or install via your usual plugin marketplace flow if applicable.

Restart Claude Code and confirm `/trade` appears in the slash-command list.

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

## Data source

All market data comes from **yfinance** (free, no API key). Technical indicators are computed via **stockstats** off the OHLCV pulled from yfinance. There is no Reddit / Twitter / Alpha Vantage integration in this initial port — the social analyst infers sentiment from news tone and recency.

## Differences from the original TradingAgents

- No LangChain / LangGraph runtime — orchestration is done by the `ta-ticker-orchestrator` subagent reading a Markdown spec.
- No multi-provider LLM client. The "LLM" is whichever Claude model is running Claude Code.
- No checkpoint / resume — runs that fail mid-pipeline can be resumed by invoking the relevant `/trade-*` sub-skill (analyst reports / research plan are persisted on disk).
- No backtesting (`backtrader`).
- Only the `yfinance` data vendor is wired up. The interface mirrors the upstream tool signatures, so adding Alpha Vantage scripts in `scripts/` later is straightforward.

## Not financial advice

This is a research / educational tool. Don't trade real money on its output.
