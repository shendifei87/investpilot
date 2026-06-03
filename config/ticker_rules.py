from typing import Literal, Tuple

# Shanghai codes: 600xxx, 601xxx, 603xxx, 605xxx, 688xxx (STAR), 689xxx (STAR)
# Shenzhen codes: 000xxx, 001xxx, 002xxx, 003xxx, 300xxx (ChiNext), 301xxx
_SHANGHAI_PREFIXES = ("60", "68")


def detect_market(ticker: str) -> Literal["US", "HK", "ASHARE"]:
    t = ticker.strip().upper()
    if t.endswith(".HK"):
        return "HK"
    if t.endswith(".SZ") or t.endswith(".SS") or t.endswith(".SH"):
        return "ASHARE"
    if t.isdigit() and len(t) == 6:
        return "ASHARE"
    return "US"


def _ashare_suffix(code: str) -> str:
    """Determine Shanghai (.SS) or Shenzhen (.SZ) from 6-digit stock code."""
    return ".SS" if code[:2] in _SHANGHAI_PREFIXES else ".SZ"


def normalize_ticker(ticker: str, market: str = None) -> Tuple[str, str]:
    if market is None:
        market = detect_market(ticker)

    t = ticker.strip().upper()

    if market == "HK":
        if t.endswith(".HK"):
            return t, market
        return f"{t}.HK", market

    if market == "ASHARE":
        if t.endswith(".SS") or t.endswith(".SZ") or t.endswith(".SH"):
            return t, market
        if t.isdigit() and len(t) == 6:
            return f"{t}{_ashare_suffix(t)}", market
        return t, market

    return t, market


def get_tushare_code(ticker: str, market: str) -> str:
    """Convert InvestPilot ticker to Tushare ts_code format.

    Tushare conventions:
      - A-share Shanghai: .SH suffix
      - A-share Shenzhen: .SZ suffix
      - HK stock: 5-digit zero-padded code, no suffix (e.g. 00700)
      - US stock: plain ticker (e.g. AAPL)
    """
    t = ticker.strip().upper()

    if market == "HK":
        # 0700.HK → 00700
        code = t.replace(".HK", "")
        return code.zfill(5)

    if market == "ASHARE":
        # Strip existing suffixes (.SS used by yfinance, .SH used by Tushare/SSE, .SZ)
        code = t.replace(".SS", "").replace(".SH", "").replace(".SZ", "")
        if not code.isdigit() or len(code) != 6:
            return t  # return as-is for non-standard codes
        # Determine Shanghai (.SH) vs Shenzhen (.SZ)
        suffix = ".SH" if code[:2] in _SHANGHAI_PREFIXES else ".SZ"
        return f"{code}{suffix}"

    # US: return ticker as-is
    return t
