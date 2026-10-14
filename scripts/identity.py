"""Resolve what an instrument is, once per run, so no agent analyzes the wrong company.

Without a ground-truth name, an agent can pattern-match a price chart to a story
and invent a different company, which then cascades through every later agent
(upstream TradingAgents #814). The vendor profile describes the instrument today,
so a past-dated run gets only its current name, marked as such: a sector or
exchange it holds today may not have held on the analysis date.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _common import is_historical, yf_retry
from symbols import asset_type

PLACEHOLDERS = {"", "none", "n/a", "nan", "null"}


def _clean(value) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return None if value.lower() in PLACEHOLDERS else value


def resolve(symbol: str) -> dict:
    """Name, sector, industry, exchange, currency and quote type; {} when the lookup fails."""
    import yfinance as yf

    try:
        info = yf_retry(lambda: yf.Ticker(symbol).info) or {}
    except Exception:
        return {}
    identity = {"name": _clean(info.get("longName")) or _clean(info.get("shortName"))}
    for src, dst in (("sector", "sector"), ("industry", "industry"), ("exchange", "exchange"),
                     ("currency", "currency"), ("quoteType", "quote_type")):
        identity[dst] = _clean(info.get(src))
    return {k: v for k, v in identity.items() if v}


def instrument_context(symbol: str, trade_date: str, identity: dict, user_symbol: str | None = None) -> str:
    kind = asset_type(symbol)
    label = {"stock": "instrument", "crypto": "crypto asset", "forex": "currency pair",
             "future": "futures contract", "index": "index"}[kind]
    text = (f"The {label} to analyze is `{symbol}`"
            + (f" (the user asked for `{user_symbol}`, which Yahoo Finance lists as `{symbol}`)" if user_symbol else "")
            + ". Refer to it by this exact symbol, keeping any exchange suffix.")
    details = []
    name = identity.get("name")
    if is_historical(trade_date):
        if name:
            details.append(f"Name: {name} (its current name, given only to identify it; "
                           f"on {trade_date} it may have been named differently)")
    else:
        if name:
            details.append(f"Name: {name}")
        sector, industry = identity.get("sector"), identity.get("industry")
        if sector or industry:
            details.append("Business: " + " / ".join(x for x in (sector, industry) if x))
        if identity.get("exchange"):
            details.append(f"Exchange: {identity['exchange']}")
    if identity.get("currency"):
        details.append(f"Prices are quoted in {identity['currency']}")
    if details:
        text += (" Resolved identity: " + "; ".join(details) + ". Do not substitute a different company "
                 "or symbol unless a tool result explicitly disproves this identity.")
    if kind == "crypto":
        text += " Treat it as a crypto asset, not a company: company fundamentals and filings do not exist for it."
    elif kind in ("forex", "future", "index"):
        text += f" It is a {label}, not a company: there are no company fundamentals, filings or insider trades."
    return text
