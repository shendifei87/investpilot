from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, List
import pandas as pd


@dataclass
class FetchResult:
    data: Optional[object] = None
    source: str = ""
    warnings: List[str] = field(default_factory=list)
    success: bool = True


class BaseFetcher(ABC):
    market: str

    @abstractmethod
    def fetch_company_info(self, ticker: str) -> FetchResult:
        ...

    @abstractmethod
    def fetch_price_history(self, ticker: str, period: str = "3y") -> FetchResult:
        ...

    @abstractmethod
    def fetch_financial_statements(self, ticker: str) -> FetchResult:
        ...

    @abstractmethod
    def fetch_valuation_inputs(self, ticker: str) -> FetchResult:
        """Fetch raw valuation inputs (price, shares, EPS, etc.) for local calculation.

        Returns raw data only — no pre-computed PE/PB/PS/EV·EBITDA ratios.
        All valuation ratios should be calculated via src.analysis.financial.calc_* functions.
        """
        ...

    def fetch_valuation_metrics(self, ticker: str) -> FetchResult:
        """Deprecated alias for fetch_valuation_inputs.

        Prefer calling fetch_valuation_inputs directly.
        """
        return self.fetch_valuation_inputs(ticker)

    def fetch_all(self, ticker: str, period: str = "5y") -> Dict[str, FetchResult]:
        results = {}
        for name, method in [
            ("company_info", self.fetch_company_info),
            ("price_history", lambda t: self.fetch_price_history(t, period=period)),
            ("financials", self.fetch_financial_statements),
            ("valuation", self.fetch_valuation_inputs),
        ]:
            try:
                results[name] = method(ticker)
            except Exception as e:
                results[name] = FetchResult(
                    success=False,
                    warnings=[f"Failed to fetch {name}: {e}"],
                )
        return results
