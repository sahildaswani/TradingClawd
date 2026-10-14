"""Map user and broker symbols to the symbols Yahoo Finance serves, and classify them.

Purely syntactic (no network), ported from upstream TradingAgents. Resolution order:
  1. Explicit aliases: spot metals and energy to their front-month future
     (XAUUSD -> GC=F), index CFD names to Yahoo index symbols (US500 -> ^GSPC).
  2. Crypto: a known base quoted in USD/USDT/USDC, dashed or not -> BASE-USD.
  3. Forex: six letters that are two ISO currency codes -> PAIR=X.
  4. Hong Kong: a numeric .HK code, zero-padded to Yahoo's 4 digits (700.HK -> 0700.HK).
  5. Shanghai: 600519.SH -> 600519.SS.
  6. Anything else: upper-cased and unchanged.
"""

import re

FOREX_CURRENCIES = frozenset({
    "USD", "EUR", "GBP", "JPY", "CHF", "CAD", "AUD", "NZD",
    "CNY", "CNH", "HKD", "SGD", "SEK", "NOK", "DKK", "PLN",
    "MXN", "ZAR", "TRY", "INR", "KRW", "BRL", "RUB", "THB",
})
CRYPTO_BASES = frozenset({"BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "BCH", "DOT", "AVAX", "LINK"})
CRYPTO_QUOTES = ("USDT", "USDC", "USD")  # longest first, so USDT/USDC match before USD

ALIASES = {
    # Precious metals (spot names -> COMEX/NYMEX futures)
    "XAUUSD": "GC=F", "XAU": "GC=F", "GOLD": "GC=F",
    "XAGUSD": "SI=F", "XAG": "SI=F", "SILVER": "SI=F",
    "XPTUSD": "PL=F", "XPDUSD": "PA=F",
    # Energy
    "WTICOUSD": "CL=F", "USOIL": "CL=F", "WTI": "CL=F",
    "BCOUSD": "BZ=F", "UKOIL": "BZ=F", "BRENT": "BZ=F",
    "NATGAS": "NG=F", "XNGUSD": "NG=F",
    "COPPER": "HG=F", "XCUUSD": "HG=F",
    # Index CFDs -> Yahoo index symbols
    "SPX500": "^GSPC", "US500": "^GSPC", "SPX": "^GSPC",
    "NAS100": "^NDX", "US100": "^NDX", "USTEC": "^NDX",
    "US30": "^DJI", "DJI30": "^DJI", "WS30": "^DJI",
    "GER40": "^GDAXI", "GER30": "^GDAXI", "DE40": "^GDAXI",
    "UK100": "^FTSE", "JP225": "^N225", "JPN225": "^N225",
    "FRA40": "^FCHI", "EU50": "^STOXX50E", "HK50": "^HSI",
}
HK_CODE = re.compile(r"^(\d{1,5})\.HK$")
SHANGHAI_SH = re.compile(r"^(\d{6})\.SH$")


def crypto_base(raw: str) -> str | None:
    """The crypto base (BTC) of BTC-USD, BTCUSD, BTC-USDT..., or None for anything else."""
    compact = raw.strip().upper().rstrip("+").replace("-", "")
    for quote in CRYPTO_QUOTES:
        if compact.endswith(quote):
            base = compact[: -len(quote)]
            return base if base in CRYPTO_BASES else None
    return None


def normalize_symbol(raw: str) -> str:
    s = raw.strip().upper().rstrip("+")  # a trailing + is a broker CFD marker
    if s in ALIASES:
        return ALIASES[s]
    base = crypto_base(s)
    if base:
        return f"{base}-USD"
    if len(s) == 6 and s[:3] in FOREX_CURRENCIES and s[3:] in FOREX_CURRENCIES:
        return f"{s}=X"
    if hk := HK_CODE.match(s):
        return f"{int(hk.group(1)):04d}.HK"
    if sh := SHANGHAI_SH.match(s):
        return f"{sh.group(1)}.SS"
    return s


def asset_type(symbol: str) -> str:
    """stock, crypto, forex, future or index, from the normalized symbol's shape."""
    if symbol.endswith("=X"):
        return "forex"
    if symbol.endswith("=F"):
        return "future"
    if symbol.startswith("^"):
        return "index"
    if crypto_base(symbol):
        return "crypto"
    return "stock"
