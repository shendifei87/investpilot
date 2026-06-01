from config.ticker_rules import normalize_ticker


def get_fetcher(ticker: str):
    normalized, market = normalize_ticker(ticker)

    if market == "US":
        from src.data.us_fetcher import USFetcher
        return USFetcher(), normalized, market
    elif market == "HK":
        from src.data.hk_fetcher import HKFetcher
        return HKFetcher(), normalized, market
    elif market == "ASHARE":
        from src.data.ashare_fetcher import AshareFetcher
        return AshareFetcher(), normalized, market
    else:
        raise ValueError(f"Unknown market for ticker: {ticker}")
