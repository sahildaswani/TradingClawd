#!/usr/bin/env python3
"""Retrieve one or more technical indicators (computed via stockstats) over a look-back window.

Supports two invocation modes:
- Single:  --indicator macd
- Batch:   --indicators macd,rsi,boll,boll_ub,boll_lb,atr,vwma,close_50_sma

Batch mode loads the underlying OHLCV once and computes every requested indicator
off the same stockstats DataFrame, avoiding redundant network downloads.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pandas as pd
import yfinance as yf
from dateutil.relativedelta import relativedelta

from _common import die, parse_date, yf_retry

# Indicator catalog — descriptions are shown to the analyst LLM
INDICATOR_DOCS = {
    "close_50_sma": (
        "50 SMA: A medium-term trend indicator. Usage: Identify trend direction and "
        "serve as dynamic support/resistance. Tips: It lags price; combine with "
        "faster indicators for timely signals."
    ),
    "close_200_sma": (
        "200 SMA: A long-term trend benchmark. Usage: Confirm overall market trend "
        "and identify golden/death cross setups. Tips: It reacts slowly; best for "
        "strategic trend confirmation rather than frequent trading entries."
    ),
    "close_10_ema": (
        "10 EMA: A responsive short-term average. Usage: Capture quick shifts in "
        "momentum and potential entry points. Tips: Prone to noise in choppy markets; "
        "use alongside longer averages for filtering false signals."
    ),
    "macd": (
        "MACD: Computes momentum via differences of EMAs. Usage: Look for crossovers "
        "and divergence as signals of trend changes. Tips: Confirm with other "
        "indicators in low-volatility or sideways markets."
    ),
    "macds": (
        "MACD Signal: An EMA smoothing of the MACD line. Usage: Use crossovers with "
        "the MACD line to trigger trades. Tips: Should be part of a broader strategy "
        "to avoid false positives."
    ),
    "macdh": (
        "MACD Histogram: Shows the gap between the MACD line and its signal. Usage: "
        "Visualize momentum strength and spot divergence early. Tips: Can be "
        "volatile; complement with additional filters in fast-moving markets."
    ),
    "rsi": (
        "RSI: Measures momentum to flag overbought/oversold conditions. Usage: Apply "
        "70/30 thresholds and watch for divergence to signal reversals. Tips: In "
        "strong trends, RSI may remain extreme; always cross-check with trend "
        "analysis."
    ),
    "boll": (
        "Bollinger Middle: A 20 SMA serving as the basis for Bollinger Bands. Usage: "
        "Acts as a dynamic benchmark for price movement. Tips: Combine with the "
        "upper and lower bands to effectively spot breakouts or reversals."
    ),
    "boll_ub": (
        "Bollinger Upper Band: Typically 2 standard deviations above the middle "
        "line. Usage: Signals potential overbought conditions and breakout zones. "
        "Tips: Confirm signals with other tools; prices may ride the band in strong "
        "trends."
    ),
    "boll_lb": (
        "Bollinger Lower Band: Typically 2 standard deviations below the middle "
        "line. Usage: Indicates potential oversold conditions. Tips: Use additional "
        "analysis to avoid false reversal signals."
    ),
    "atr": (
        "ATR: Averages true range to measure volatility. Usage: Set stop-loss levels "
        "and adjust position sizes based on current market volatility. Tips: It's a "
        "reactive measure, so use it as part of a broader risk management strategy."
    ),
    "vwma": (
        "VWMA: A moving average weighted by volume. Usage: Confirm trends by "
        "integrating price action with volume data. Tips: Watch for skewed results "
        "from volume spikes; use in combination with other volume analyses."
    ),
    "mfi": (
        "MFI: The Money Flow Index is a momentum indicator that uses both price and "
        "volume to measure buying and selling pressure. Usage: Identify overbought "
        "(>80) or oversold (<20) conditions and confirm the strength of trends or "
        "reversals. Tips: Use alongside RSI or MACD to confirm signals; divergence "
        "between price and MFI can indicate potential reversals."
    ),
}


def _load_ohlcv(symbol: str, curr_date: str) -> pd.DataFrame:
    """Fetch ~5 years of OHLCV and filter to curr_date to prevent look-ahead bias."""
    today = pd.Timestamp.today()
    start = today - pd.DateOffset(years=5)
    data = yf_retry(
        lambda: yf.download(
            symbol,
            start=start.strftime("%Y-%m-%d"),
            end=today.strftime("%Y-%m-%d"),
            multi_level_index=False,
            progress=False,
            auto_adjust=True,
        )
    )
    data = data.reset_index()
    data["Date"] = pd.to_datetime(data["Date"], errors="coerce")
    data = data.dropna(subset=["Date"])

    price_cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in data.columns]
    data[price_cols] = data[price_cols].apply(pd.to_numeric, errors="coerce")
    data = data.dropna(subset=["Close"])
    data[price_cols] = data[price_cols].ffill().bfill()

    cutoff = pd.to_datetime(curr_date)
    return data[data["Date"] <= cutoff]


def _format_indicator_section(
    indicator: str,
    df_with_dates: pd.DataFrame,
    curr_dt: pd.Timestamp,
    before: pd.Timestamp,
    curr_date: str,
) -> str:
    """Build the markdown section for one indicator off an already-wrapped DataFrame."""
    value_map = {}
    for _, row in df_with_dates.iterrows():
        v = row[indicator]
        value_map[row["Date"]] = "N/A" if pd.isna(v) else str(v)

    lines = []
    cur = curr_dt
    while cur >= before:
        ds = cur.strftime("%Y-%m-%d")
        if ds in value_map:
            lines.append(f"{ds}: {value_map[ds]}")
        else:
            lines.append(f"{ds}: N/A: Not a trading day (weekend or holiday)")
        cur = cur - relativedelta(days=1)

    return (
        f"## {indicator} values from {before.strftime('%Y-%m-%d')} to {curr_date}:\n\n"
        + "\n".join(lines)
        + "\n\n"
        + INDICATOR_DOCS[indicator]
    )


def get_indicators_batch(
    symbol: str, indicators: list[str], curr_date: str, look_back: int
) -> str:
    """Compute one or more indicators with a single OHLCV download."""
    unknown = [i for i in indicators if i not in INDICATOR_DOCS]
    if unknown:
        raise ValueError(
            f"Unsupported indicator(s): {', '.join(unknown)}. "
            f"Choose from: {', '.join(INDICATOR_DOCS.keys())}"
        )
    if not indicators:
        raise ValueError("At least one indicator must be requested.")

    parse_date(curr_date)
    curr_dt = pd.to_datetime(curr_date)
    before = curr_dt - relativedelta(days=look_back)

    from stockstats import wrap

    data = _load_ohlcv(symbol, curr_date)
    if data.empty:
        raise RuntimeError(f"No OHLCV data available for {symbol} up to {curr_date}")

    df = wrap(data)
    df["Date"] = df["Date"].dt.strftime("%Y-%m-%d")

    # Trigger stockstats to compute every requested indicator off the same wrapped df
    for ind in indicators:
        df[ind]

    sections = [
        _format_indicator_section(ind, df, curr_dt, before, curr_date)
        for ind in indicators
    ]
    return "\n\n".join(sections)


def get_indicator(symbol: str, indicator: str, curr_date: str, look_back: int) -> str:
    """Backward-compat single-indicator wrapper."""
    return get_indicators_batch(symbol, [indicator], curr_date, look_back)


def _parse_indicator_list(s: str) -> list[str]:
    return [piece.strip() for piece in s.split(",") if piece.strip()]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--symbol", required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--indicator",
        help=f"Single indicator. One of: {', '.join(INDICATOR_DOCS.keys())}",
    )
    group.add_argument(
        "--indicators",
        help=(
            "Comma-separated list of indicators to compute in a single OHLCV pass, "
            "e.g. 'macd,rsi,boll,boll_ub,boll_lb,atr,vwma,close_50_sma'."
        ),
    )
    p.add_argument("--curr-date", required=True, help="YYYY-MM-DD")
    p.add_argument("--look-back", type=int, default=30)
    args = p.parse_args()

    indicators = (
        [args.indicator] if args.indicator else _parse_indicator_list(args.indicators)
    )

    try:
        print(get_indicators_batch(args.symbol, indicators, args.curr_date, args.look_back))
    except Exception as e:
        die(str(e))


if __name__ == "__main__":
    main()
