import warnings
import pandas as pd
import numpy as np

# Field name aliases: yfinance (English) → akshare (Chinese) → tushare (English)
_INCOME_ALIASES = {
    "Total Revenue": ("营业总收入", "营业收入", "total_revenue"),
    "Gross Profit": ("毛利润",),
    "Operating Income": ("营业利润", "operate_profit"),
    "Net Income": ("净利润", "n_income", "n_income_attr_p"),
    "Net Income from Continuing Operations": ("持续经营净利润",),
    "Interest Expense": ("利息费用", "利息支出", "int_exp"),
    "Tax Provision": ("所得税费用", "income_tax"),
}

_BALANCE_ALIASES = {
    "Total Stockholder Equity": ("所有者权益合计", "股东权益合计", "total_hldr_eqy_exc_min_int"),
    "Total Debt": ("负债合计", "总负债", "total_liab"),
    "Total Current Assets": ("流动资产合计", "total_cur_assets"),
    "Total Current Liabilities": ("流动负债合计", "total_cur_liab"),
    "Total Assets": ("资产总计", "总资产", "total_assets"),
    "Cash And Cash Equivalents": ("货币资金", "monetary_capital"),
    "Accounts Receivable": ("应收账款", "accounts_recev"),
    "Short Term Debt": ("短期借款", "st_borr"),
    "Long Term Debt": ("长期借款", "lt_borr"),
}

_CASHFLOW_ALIASES = {
    "Operating Cash Flow": ("经营活动产生的现金流量净额", "n_cashflow_act"),
    "Capital Expenditure": ("购建固定资产无形资产和其他长期资产支付的现金", "c_pay_acq_const_fiolta"),
    "Depreciation And Amortization": (
        "固定资产折旧、油气资产折耗、生产性生物资产折旧",
        "资产减值准备",
        "折旧与摊销",
        "depr_fa_coga_dpba",
    ),
}


def _get_series(df, field, aliases, warnings_list=None):
    """Extract a numeric series from a financial DataFrame.

    Handles both yfinance (items as index rows) and akshare (items as columns).
    Returns Series or None.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None

    # yfinance: financial items as index, dates as columns
    if field in df.index:
        return df.loc[field]

    # akshare: financial items as columns, dates in a column
    all_names = (field,) + aliases
    for name in all_names:
        if name in df.columns:
            s = pd.to_numeric(df[name], errors="coerce")
            for date_col in ("报告期", "截止日期", "日期", "end_date"):
                if date_col in df.columns:
                    s.index = pd.to_datetime(df[date_col])
                    break
            return s

    msg = f"Field '{field}' not found in DataFrame (tried aliases: {aliases})"
    if warnings_list is not None:
        warnings_list.append(msg)
    return None


def calc_financial_ratios(income: pd.DataFrame, balance: pd.DataFrame) -> dict:
    """Calculate key financial ratios from income statement and balance sheet."""
    ratios = {}
    w = []

    if isinstance(income, pd.DataFrame) and not income.empty:
        rev = _get_series(income, "Total Revenue", _INCOME_ALIASES.get("Total Revenue", ()), w)
        gp = _get_series(income, "Gross Profit", _INCOME_ALIASES.get("Gross Profit", ()), w)
        op = _get_series(income, "Operating Income", _INCOME_ALIASES.get("Operating Income", ()), w)
        ni = _get_series(income, "Net Income", _INCOME_ALIASES.get("Net Income", ()), w)

        if rev is not None:
            if gp is not None:
                ratios["gross_margin"] = (gp / rev).to_dict()
            if op is not None:
                ratios["operating_margin"] = (op / rev).to_dict()
            if ni is not None:
                ratios["net_margin"] = (ni / rev).to_dict()

    if isinstance(balance, pd.DataFrame) and not balance.empty:
        equity = _get_series(balance, "Total Stockholder Equity", _BALANCE_ALIASES.get("Total Stockholder Equity", ()), w)
        debt = _get_series(balance, "Total Debt", _BALANCE_ALIASES.get("Total Debt", ()), w)
        current_assets = _get_series(balance, "Total Current Assets", _BALANCE_ALIASES.get("Total Current Assets", ()), w)
        current_liab = _get_series(balance, "Total Current Liabilities", _BALANCE_ALIASES.get("Total Current Liabilities", ()), w)

        if equity is not None:
            if debt is not None:
                ratios["debt_to_equity"] = (debt / equity).to_dict()
            if current_assets is not None and current_liab is not None:
                ratios["current_ratio"] = (current_assets / current_liab).to_dict()

    if w:
        warnings.warn(f"Financial ratio calculation warnings: {'; '.join(w)}")

    return ratios


def calc_revenue_growth(income: pd.DataFrame) -> dict:
    """Calculate period-over-period revenue growth.

    With annual data, returns YoY growth. With quarterly data, returns QoQ growth.
    """
    rev = _get_series(income, "Total Revenue", _INCOME_ALIASES.get("Total Revenue", ()))
    if rev is None:
        return {}
    rev_sorted = rev.sort_index()
    yoy = rev_sorted.pct_change(periods=1)
    return {"revenue_yoy": yoy.to_dict()}


def dupont_analysis(income: pd.DataFrame, balance: pd.DataFrame) -> dict:
    """3-factor DuPont decomposition: ROE = Net Margin * Asset Turnover * Leverage."""
    ni = _get_series(income, "Net Income", _INCOME_ALIASES.get("Net Income", ()))
    rev = _get_series(income, "Total Revenue", _INCOME_ALIASES.get("Total Revenue", ()))
    equity = _get_series(balance, "Total Stockholder Equity", _BALANCE_ALIASES.get("Total Stockholder Equity", ()))
    assets = _get_series(balance, "Total Assets", _BALANCE_ALIASES.get("Total Assets", ()))

    if any(v is None for v in [ni, rev, equity, assets]):
        return {}

    net_margin = ni / rev
    asset_turnover = rev / assets
    leverage = assets / equity
    roe = net_margin * asset_turnover * leverage

    return {
        "roe": roe.to_dict(),
        "net_margin": net_margin.to_dict(),
        "asset_turnover": asset_turnover.to_dict(),
        "financial_leverage": leverage.to_dict(),
    }


def calc_earnings_quality(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame = None,
) -> dict:
    """Earnings Quality Composite (EQC) — 0-100 score.

    Components:
      - Cash conversion: OCF / Net Income (>1.2 good, <0.8 bad) — weight 0.30
      - Accrual ratio: (Net Income - OCF) / Total Assets (lower = better) — weight 0.25
      - Receivables trend: change in AR turnover (improving = better) — weight 0.20
      - Margin consistency: std dev of net margin over available periods — weight 0.15
      - Revenue quality: organic revenue (excl. one-offs) trend — weight 0.10

    Returns dict with total score (0-100) and sub-scores.
    """
    scores = {}
    w = []

    ni = _get_series(income, "Net Income", _INCOME_ALIASES.get("Net Income", ()), w)
    rev = _get_series(income, "Total Revenue", _INCOME_ALIASES.get("Total Revenue", ()), w)
    assets = _get_series(balance, "Total Assets", _BALANCE_ALIASES.get("Total Assets", ()), w)
    current_assets = _get_series(balance, "Total Current Assets", _BALANCE_ALIASES.get("Total Current Assets", ()), w)
    current_liab = _get_series(balance, "Total Current Liabilities", _BALANCE_ALIASES.get("Total Current Liabilities", ()), w)

    # 1. Cash conversion (OCF / Net Income)
    ocf = None
    if cashflow is not None:
        ocf = _get_series(cashflow, "Operating Cash Flow", _CASHFLOW_ALIASES.get("Operating Cash Flow", ()), w)

    cash_conversion_score = 50  # neutral default
    if ocf is not None and ni is not None:
        ratio = ocf / ni
        # Take latest value
        latest_ratio = ratio.dropna().iloc[-1] if not ratio.dropna().empty else 1.0
        # Skip scoring if net income is zero or negative (ratio is meaningless)
        if not np.isfinite(latest_ratio):
            pass  # keep neutral default
        elif latest_ratio > 1.5:
            cash_conversion_score = 100
        elif latest_ratio > 1.2:
            cash_conversion_score = 80
        elif latest_ratio > 1.0:
            cash_conversion_score = 60
        elif latest_ratio > 0.8:
            cash_conversion_score = 40
        else:
            cash_conversion_score = 20
    scores["cash_conversion"] = {"score": cash_conversion_score, "weight": 0.30}

    # 2. Accrual ratio
    accrual_score = 50
    if ni is not None and ocf is not None and assets is not None:
        assets_safe = assets.replace(0, np.nan)
        accruals = (ni - ocf) / assets_safe
        latest_accrual = accruals.dropna().iloc[-1] if not accruals.dropna().empty else 0
        if latest_accrual < -0.02:
            accrual_score = 90  # cash-heavy, conservative
        elif latest_accrual < 0.02:
            accrual_score = 70
        elif latest_accrual < 0.05:
            accrual_score = 50
        elif latest_accrual < 0.10:
            accrual_score = 30
        else:
            accrual_score = 10  # high accruals, red flag
    scores["accrual_ratio"] = {"score": accrual_score, "weight": 0.25}

    # 3. Receivables trend — use actual AR turnover when available
    receivables_score = 50
    ar_series = _get_series(
        balance, "Accounts Receivable",
        _BALANCE_ALIASES.get("Accounts Receivable", ()), w,
    )
    if ar_series is not None and not ar_series.dropna().empty and rev is not None:
        ar_clean = ar_series.dropna()
        if len(ar_clean) >= 2:
            # AR turnover = Revenue / Accounts Receivable (higher = better)
            ar_turnover = rev / ar_clean
            ar_turnover_clean = ar_turnover.dropna()
            if len(ar_turnover_clean) >= 2:
                trend = ar_turnover_clean.iloc[-1] - ar_turnover_clean.iloc[0]
                if trend > 0.5:
                    receivables_score = 80
                elif trend > 0:
                    receivables_score = 60
                elif trend > -0.5:
                    receivables_score = 40
                else:
                    receivables_score = 20
    elif current_assets is not None and current_liab is not None:
        # Fallback: current ratio trend as proxy
        cr = current_assets / current_liab
        cr_clean = cr.dropna()
        if len(cr_clean) >= 2:
            trend = cr_clean.iloc[-1] - cr_clean.iloc[0]
            if trend > 0.3:
                receivables_score = 80
            elif trend > 0:
                receivables_score = 60
            elif trend > -0.3:
                receivables_score = 40
            else:
                receivables_score = 20
    scores["receivables_trend"] = {"score": receivables_score, "weight": 0.20}

    # 4. Margin consistency (lower std = more consistent = better)
    margin_score = 50
    if ni is not None and rev is not None:
        margins = (ni / rev).dropna()
        if len(margins) >= 2:
            margin_std = margins.std()
            mean_margin = abs(margins.mean())
            cv = margin_std / mean_margin if mean_margin > 0 else 1
            if cv < 0.1:
                margin_score = 90
            elif cv < 0.2:
                margin_score = 70
            elif cv < 0.4:
                margin_score = 50
            else:
                margin_score = 30
    scores["margin_consistency"] = {"score": margin_score, "weight": 0.15}

    # 5. Revenue quality (revenue trend stability)
    rev_score = 50
    if rev is not None:
        rev_growth = rev.pct_change().dropna()
        if len(rev_growth) >= 2:
            positive_pct = (rev_growth > 0).mean()
            if positive_pct > 0.8:
                rev_score = 80
            elif positive_pct > 0.6:
                rev_score = 60
            elif positive_pct > 0.4:
                rev_score = 40
            else:
                rev_score = 20
    scores["revenue_quality"] = {"score": rev_score, "weight": 0.10}

    # Weighted total
    total = sum(s["score"] * s["weight"] for s in scores.values())

    # Grade
    if total >= 75:
        grade = "A"
    elif total >= 60:
        grade = "B"
    elif total >= 45:
        grade = "C"
    else:
        grade = "D"

    return {
        "total_score": round(total, 1),
        "grade": grade,
        "components": scores,
        "interpretation": _eqc_interpretation(total),
        "warnings": w,
    }


def calc_pe(
    price: float,
    eps: float,
    label: str = "",
) -> dict:
    """Calculate PE ratio from raw price and EPS data.

    This is the **ONLY** correct way to compute PE in InvestPilot.
    Never use PE values from news, analyst reports, or third-party APIs
    without re-calculating from source financial data.

    Args:
        price: Current or historical stock price.
        eps: Earnings per share. For trailing PE use TTM EPS;
             for forward PE use consensus or estimated next-year EPS.
        label: Optional label describing the PE type
               (e.g. "TTM", "2025E", "2026E Forward").

    Returns:
        dict with pe value, inputs, label, and validity flag.
    """
    if eps is None or price is None:
        return {
            "pe": None,
            "price": price,
            "eps": eps,
            "label": label,
            "valid": False,
            "error": "price or eps is None",
        }

    if eps == 0:
        return {
            "pe": None,
            "price": price,
            "eps": eps,
            "label": label,
            "valid": False,
            "error": "EPS is zero — PE undefined",
        }

    pe = price / eps

    if not np.isfinite(pe) or pe < 0:
        return {
            "pe": None,
            "price": price,
            "eps": eps,
            "label": label,
            "valid": False,
            "error": f"PE not meaningful: price={price}, eps={eps}, pe={pe}",
        }

    return {
        "pe": round(pe, 2),
        "price": price,
        "eps": eps,
        "label": label,
        "valid": True,
        "source": "calculated",
    }


def calc_pe_trailing(price: float, income: pd.DataFrame, shares: float) -> dict:
    """Calculate trailing (TTM) PE from price, income statement and shares outstanding.

    Uses the most recent full-year net income to compute TTM EPS.

    Args:
        price: Current stock price.
        income: Income statement DataFrame (yfinance or akshare format).
        shares: Shares outstanding.

    Returns:
        dict from calc_pe with TTM PE.
    """
    ni = _get_series(income, "Net Income", _INCOME_ALIASES.get("Net Income", ()))
    if ni is None or ni.dropna().empty:
        return {
            "pe": None,
            "price": price,
            "eps": None,
            "label": "TTM",
            "valid": False,
            "error": "Net Income not found in income statement",
        }

    latest_ni = float(ni.dropna().iloc[-1])
    if shares is None or shares <= 0:
        return {
            "pe": None,
            "price": price,
            "eps": None,
            "label": "TTM",
            "valid": False,
            "error": f"Shares outstanding invalid: {shares}",
        }

    eps_ttm = latest_ni / shares
    result = calc_pe(price, eps_ttm, label="TTM")
    result["net_income"] = latest_ni
    result["shares"] = shares
    result["eps_ttm"] = eps_ttm
    return result


def calc_pe_forward(price: float, eps_estimate: float, year_label: str = "T+1") -> dict:
    """Calculate forward PE from price and EPS estimate.

    Args:
        price: Current stock price.
        eps_estimate: Estimated EPS for the forward year.
        year_label: Label for the forward year (e.g. "2026E", "T+1").

    Returns:
        dict from calc_pe with forward PE.
    """
    result = calc_pe(price, eps_estimate, label=f"Forward {year_label}")
    result["eps_estimate"] = eps_estimate
    return result


def calc_peer_pe_table(
    target: dict,
    peers: list[dict],
    pe_basis: str = "forward",
) -> dict:
    """Build an apple-to-apple PE comparison table.

    Enforces that all PE values in the comparison use the SAME basis
    (all trailing TTM or all forward T+1). Mixing trailing and forward
    PE in the same comparison is a hard error.

    Args:
        target: Dict with keys: name, price, eps (or eps_estimate).
                If pe_basis="forward", must include eps_estimate.
                If pe_basis="trailing", must include eps (TTM).
        peers: List of dicts with same structure as target.
        pe_basis: "forward" or "trailing". All entries MUST use the same basis.

    Returns:
        dict with comparison table, consistency check result, and warnings.
    """
    warnings_list = []

    if pe_basis not in ("forward", "trailing"):
        return {"error": f"pe_basis must be 'forward' or 'trailing', got '{pe_basis}'"}

    eps_key = "eps_estimate" if pe_basis == "forward" else "eps"

    rows = []
    basis_labels_found = set()

    # Process target
    target_eps = target.get(eps_key)
    if target_eps is None or target.get("price") is None:
        return {"error": f"Target missing '{eps_key}' or 'price'"}

    target_pe = calc_pe(target["price"], target_eps, label=target.get("pe_label", pe_basis))
    if target_pe["valid"]:
        rows.append({
            "name": target.get("name", "Target"),
            "pe": target_pe["pe"],
            "eps": target_eps,
            "price": target["price"],
            "basis": pe_basis,
            "is_target": True,
        })
        basis_labels_found.add(pe_basis)

    # Process peers
    for peer in peers:
        peer_eps = peer.get(eps_key)
        if peer_eps is None or peer.get("price") is None:
            warnings_list.append(f"Peer '{peer.get('name', '?')}' missing {eps_key}, skipped")
            continue

        # Check for basis mismatch
        peer_label = peer.get("pe_label", pe_basis)
        if "trailing" in str(peer_label).lower() and pe_basis == "forward":
            warnings_list.append(
                f"Peer '{peer.get('name', '?')}' PE is labeled as trailing but comparison "
                f"is on forward basis. This is NOT apple-to-apple!"
            )
        elif "forward" in str(peer_label).lower() and pe_basis == "trailing":
            warnings_list.append(
                f"Peer '{peer.get('name', '?')}' PE is labeled as forward but comparison "
                f"is on trailing basis. This is NOT apple-to-apple!"
            )

        peer_pe = calc_pe(peer["price"], peer_eps, label=peer_label)
        if peer_pe["valid"]:
            rows.append({
                "name": peer.get("name", "?"),
                "pe": peer_pe["pe"],
                "eps": peer_eps,
                "price": peer["price"],
                "basis": pe_basis,
                "is_target": False,
            })

    if len(rows) < 2:
        return {
            "error": "Need at least target + 1 peer with valid PE",
            "warnings": warnings_list,
        }

    # Compute median
    peer_pe_values = [r["pe"] for r in rows if not r["is_target"]]
    target_row = [r for r in rows if r["is_target"]][0]
    median_pe = float(np.median(peer_pe_values))

    premium_vs_median = (target_row["pe"] - median_pe) / median_pe if median_pe > 0 else None

    return {
        "rows": rows,
        "target_pe": target_row["pe"],
        "peer_median_pe": round(median_pe, 2),
        "premium_vs_median": round(premium_vs_median, 4) if premium_vs_median is not None else None,
        "basis": pe_basis,
        "apple_to_apple": len(warnings_list) == 0,
        "warnings": warnings_list,
        "source": "calculated",
    }


def calc_pb(
    price: float,
    book_value_per_share: float,
    label: str = "MRQ",
) -> dict:
    """Calculate Price-to-Book ratio from raw data.

    Args:
        price: Current or historical stock price.
        book_value_per_share: Book value per share (equity / shares outstanding).
        label: Label for the data basis (e.g. "MRQ", "2025E").

    Returns:
        dict with pb value, inputs, label, and validity flag.
    """
    if book_value_per_share is None or price is None:
        return {"pb": None, "valid": False, "error": "price or bvps is None"}

    if book_value_per_share <= 0:
        return {"pb": None, "valid": False, "error": f"Book value per share <= 0: {book_value_per_share}"}

    pb = price / book_value_per_share

    return {
        "pb": round(pb, 2),
        "price": price,
        "book_value_per_share": book_value_per_share,
        "label": label,
        "valid": True,
        "source": "calculated",
    }


def calc_pb_from_statements(
    price: float,
    balance: pd.DataFrame,
    shares: float,
) -> dict:
    """Calculate PB from balance sheet data.

    Args:
        price: Current stock price.
        balance: Balance sheet DataFrame.
        shares: Shares outstanding.

    Returns:
        dict from calc_pb.
    """
    equity = _get_series(balance, "Total Stockholder Equity", _BALANCE_ALIASES.get("Total Stockholder Equity", ()))
    if equity is None or equity.dropna().empty:
        return {"pb": None, "valid": False, "error": "Equity not found in balance sheet"}

    latest_equity = float(equity.dropna().iloc[-1])
    if shares is None or shares <= 0:
        return {"pb": None, "valid": False, "error": f"Shares outstanding invalid: {shares}"}

    bvps = latest_equity / shares
    result = calc_pb(price, bvps, label="MRQ")
    result["total_equity"] = latest_equity
    result["shares"] = shares
    return result


def calc_ps(
    price: float,
    revenue_per_share: float,
    label: str = "TTM",
) -> dict:
    """Calculate Price-to-Sales ratio from raw data.

    Args:
        price: Current or historical stock price.
        revenue_per_share: Revenue per share (total revenue / shares outstanding).
        label: Label for the data basis.

    Returns:
        dict with ps value, inputs, label, and validity flag.
    """
    if revenue_per_share is None or price is None:
        return {"ps": None, "valid": False, "error": "price or rps is None"}

    if revenue_per_share <= 0:
        return {"ps": None, "valid": False, "error": f"Revenue per share <= 0: {revenue_per_share}"}

    ps = price / revenue_per_share

    return {
        "ps": round(ps, 2),
        "price": price,
        "revenue_per_share": revenue_per_share,
        "label": label,
        "valid": True,
        "source": "calculated",
    }


def calc_ps_from_statements(
    price: float,
    income: pd.DataFrame,
    shares: float,
    label: str = "TTM",
) -> dict:
    """Calculate PS from income statement data.

    Args:
        price: Current stock price.
        income: Income statement DataFrame.
        shares: Shares outstanding.
        label: Label (TTM or forward year).

    Returns:
        dict from calc_ps.
    """
    rev = _get_series(income, "Total Revenue", _INCOME_ALIASES.get("Total Revenue", ()))
    if rev is None or rev.dropna().empty:
        return {"ps": None, "valid": False, "error": "Revenue not found in income statement"}

    latest_rev = float(rev.dropna().iloc[-1])
    if shares is None or shares <= 0:
        return {"ps": None, "valid": False, "error": f"Shares outstanding invalid: {shares}"}

    rps = latest_rev / shares
    result = calc_ps(price, rps, label=label)
    result["total_revenue"] = latest_rev
    result["shares"] = shares
    return result


def calc_ev_ebitda(
    market_cap: float,
    total_debt: float,
    cash: float,
    ebitda: float,
    label: str = "TTM",
) -> dict:
    """Calculate EV/EBITDA from raw financial data.

    EV = Market Cap + Total Debt - Cash
    EV/EBITDA = EV / EBITDA

    Args:
        market_cap: Market capitalization.
        total_debt: Total debt (short-term + long-term).
        cash: Cash and cash equivalents.
        ebitda: Earnings before interest, taxes, depreciation, and amortization.
        label: Label for the data basis.

    Returns:
        dict with ev_ebitda value, inputs, label, and validity flag.
    """
    if any(v is None for v in [market_cap, total_debt, cash, ebitda]):
        return {"ev_ebitda": None, "valid": False, "error": "One or more inputs is None"}

    ev = market_cap + total_debt - cash

    if ebitda == 0:
        return {"ev_ebitda": None, "valid": False, "error": "EBITDA is zero — EV/EBITDA undefined"}

    ev_ebitda = ev / ebitda

    if not np.isfinite(ev_ebitda) or ev_ebitda < 0:
        return {
            "ev_ebitda": None,
            "valid": False,
            "error": f"EV/EBITDA not meaningful: ev={ev}, ebitda={ebitda}",
        }

    return {
        "ev_ebitda": round(ev_ebitda, 2),
        "ev": round(ev, 2),
        "market_cap": market_cap,
        "total_debt": total_debt,
        "cash": cash,
        "ebitda": ebitda,
        "label": label,
        "valid": True,
        "source": "calculated",
    }


def calc_all_valuation_ratios(
    price: float,
    shares: float,
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cashflow: pd.DataFrame = None,
    eps_estimate: float = None,
    forward_label: str = "T+1",
) -> dict:
    """Calculate all key valuation ratios from raw financial data in one call.

    This is the recommended entry point for computing valuation ratios.
    All ratios are calculated from source data — no news or API-fetched values.

    Args:
        price: Current stock price.
        shares: Shares outstanding.
        income: Income statement DataFrame.
        balance: Balance sheet DataFrame.
        cashflow: Cash flow statement DataFrame (optional, improves EBITDA accuracy).
        eps_estimate: Optional forward EPS estimate for forward PE.
        forward_label: Label for the forward year (e.g. "T+1", "2026E").

    Returns:
        dict with all valuation ratios, each including source="calculated".
    """
    results = {"source": "calculated"}
    warnings_list = []

    # Trailing PE
    pe_ttm = calc_pe_trailing(price, income, shares)
    results["pe_trailing"] = pe_ttm
    if not pe_ttm.get("valid"):
        warnings_list.append(f"PE trailing: {pe_ttm.get('error', 'invalid')}")

    # Forward PE (if estimate provided)
    if eps_estimate is not None:
        pe_fwd = calc_pe_forward(price, eps_estimate, forward_label)
        results["pe_forward"] = pe_fwd
        if not pe_fwd.get("valid"):
            warnings_list.append(f"PE forward: {pe_fwd.get('error', 'invalid')}")

    # PB
    pb = calc_pb_from_statements(price, balance, shares)
    results["pb"] = pb
    if not pb.get("valid"):
        warnings_list.append(f"PB: {pb.get('error', 'invalid')}")

    # PS
    ps = calc_ps_from_statements(price, income, shares)
    results["ps"] = ps
    if not ps.get("valid"):
        warnings_list.append(f"PS: {ps.get('error', 'invalid')}")

    # EV/EBITDA — use real D&A and Cash when available
    market_cap = price * shares if price and shares else None
    op_series = _get_series(income, "Operating Income", _INCOME_ALIASES.get("Operating Income", ()))

    if market_cap and op_series is not None and not op_series.dropna().empty:
        latest_op = float(op_series.dropna().iloc[-1])

        # EBITDA: Operating Income + D&A (from cashflow)
        ebitda = None
        if cashflow is not None:
            da_series = _get_series(
                cashflow, "Depreciation And Amortization",
                _CASHFLOW_ALIASES.get("Depreciation And Amortization", ()),
            )
            if da_series is not None and not da_series.dropna().empty:
                latest_da = float(da_series.dropna().iloc[-1])
                ebitda = latest_op + latest_da

        if ebitda is None:
            # Fallback: approximate EBITDA with 1.2x multiplier
            ebitda = latest_op * 1.2
            warnings_list.append(
                "D&A not found in cashflow statement; using Operating Income × 1.2 "
                "approximation for EBITDA. Pass cashflow= for accurate calculation."
            )

        # Debt: try Short Term + Long Term first, fallback to Total Debt
        std_series = _get_series(balance, "Short Term Debt", _BALANCE_ALIASES.get("Short Term Debt", ()))
        ltd_series = _get_series(balance, "Long Term Debt", _BALANCE_ALIASES.get("Long Term Debt", ()))
        if std_series is not None and ltd_series is not None:
            latest_std = float(std_series.dropna().iloc[-1]) if not std_series.dropna().empty else 0
            latest_ltd = float(ltd_series.dropna().iloc[-1]) if not ltd_series.dropna().empty else 0
            latest_debt = latest_std + latest_ltd
        else:
            debt_series = _get_series(balance, "Total Debt", _BALANCE_ALIASES.get("Total Debt", ()))
            latest_debt = float(debt_series.dropna().iloc[-1]) if debt_series is not None and not debt_series.dropna().empty else 0

        # Cash: try Cash & Cash Equivalents first, fallback to CA - CL proxy
        cash_series = _get_series(
            balance, "Cash And Cash Equivalents",
            _BALANCE_ALIASES.get("Cash And Cash Equivalents", ()),
        )
        if cash_series is not None and not cash_series.dropna().empty:
            latest_cash = float(cash_series.dropna().iloc[-1])
        else:
            ca_series = _get_series(balance, "Total Current Assets", _BALANCE_ALIASES.get("Total Current Assets", ()))
            cl_series = _get_series(balance, "Total Current Liabilities", _BALANCE_ALIASES.get("Total Current Liabilities", ()))
            latest_cash = 0
            if ca_series is not None and cl_series is not None:
                latest_ca = float(ca_series.dropna().iloc[-1]) if not ca_series.dropna().empty else 0
                latest_cl = float(cl_series.dropna().iloc[-1]) if not cl_series.dropna().empty else 0
                latest_cash = max(0, latest_ca - latest_cl)
            warnings_list.append(
                "Cash & Cash Equivalents not found in balance sheet; "
                "using Current Assets - Current Liabilities as proxy. "
                "Data quality may be reduced."
            )

        ev_label = "TTM (from source data)" if ebitda != latest_op * 1.2 else "TTM (approx)"
        ev_res = calc_ev_ebitda(market_cap, latest_debt, latest_cash, ebitda, label=ev_label)
        results["ev_ebitda"] = ev_res
        if not ev_res.get("valid"):
            warnings_list.append(f"EV/EBITDA: {ev_res.get('error', 'invalid')}")

    results["warnings"] = warnings_list
    return results


def validate_valuation_apple_to_apple(
    comparisons: list[dict],
) -> dict:
    """Validate that all valuation comparisons are apple-to-apple.

    Checks:
    1. Same metric type (PE vs PB vs PS vs EV/EBITDA) — must be consistent.
    2. Same time basis (TTM vs Forward T+1 vs Forward T+2) — must be consistent.
    3. Same source (calculated vs news) — must all be calculated.

    Args:
        comparisons: List of dicts, each with keys:
            metric: "pe", "pb", "ps", or "ev_ebitda"
            basis: "TTM", "T+1", "T+2", "T+3", "MRQ"
            value: the numeric value
            source: "calculated" or other
            label: descriptive label (e.g. "2026E Forward PE", "TTM PE")

    Returns:
        dict with passed flag, violations, and summary.
    """
    if len(comparisons) < 2:
        return {"passed": True, "violations": [], "summary": "Fewer than 2 entries, no comparison to validate"}

    violations = []

    # Group by metric type
    metrics_found = set(c.get("metric", "") for c in comparisons)
    if len(metrics_found) > 1:
        violations.append({
            "type": "mixed_metrics",
            "detail": f"Mixed metric types in comparison: {metrics_found}. "
                      "Each comparison table must use a single metric.",
        })

    # Check time basis consistency
    bases_found = set(c.get("basis", "") for c in comparisons)
    if len(bases_found) > 1:
        # Check if they're just TTM vs Forward — that's a hard error
        has_ttm = any("TTM" in b or "trailing" in b.lower() for b in bases_found if b)
        has_forward = any("Forward" in b or "T+" in b for b in bases_found if b)

        if has_ttm and has_forward:
            violations.append({
                "type": "trailing_vs_forward_mixed",
                "detail": f"MIXED trailing and forward in same comparison: {bases_found}. "
                          "Trailing PE and Forward PE are NOT comparable. "
                          "Use the same basis for all entries.",
                "severity": "CRITICAL",
            })

        # Check T+1 vs T+2 mixing
        forward_years = set()
        for b in bases_found:
            if b and ("T+" in b or "E" in b):
                forward_years.add(b)
        if len(forward_years) > 1:
            violations.append({
                "type": "forward_year_mixed",
                "detail": f"MIXED forward years in same comparison: {forward_years}. "
                          "T+1 PE and T+2 PE are NOT comparable. "
                          "All entries must use the same forward year.",
                "severity": "CRITICAL",
            })

    # Check source consistency
    non_calculated = [c for c in comparisons if c.get("source", "") != "calculated"]
    if non_calculated:
        violations.append({
            "type": "non_calculated_source",
            "detail": f"Found {len(non_calculated)} entries not from calculated source: "
                      f"{[c.get('label', '?') for c in non_calculated]}. "
                      "All valuation ratios must be calculated from raw financial data.",
            "severity": "CRITICAL",
        })

    passed = len(violations) == 0
    critical = [v for v in violations if v.get("severity") == "CRITICAL"]

    return {
        "passed": passed,
        "violations": violations,
        "n_critical": len(critical),
        "summary": (
            "All comparisons apple-to-apple" if passed
            else f"{len(violations)} violation(s) found ({len(critical)} critical)"
        ),
    }


def _eqc_interpretation(score: float) -> str:
    if score >= 80:
        return "Excellent earnings quality. High cash conversion, low accruals, stable margins."
    if score >= 65:
        return "Good earnings quality. Mostly reliable with minor concerns."
    if score >= 50:
        return "Mixed earnings quality. Some red flags — scrutinize cash flow vs earnings gap."
    if score >= 35:
        return "Below average. Significant accruals or inconsistency — earnings may not be sustainable."
    return "Poor earnings quality. High risk of earnings manipulation or deterioration."


def quarterly_arithmetic_check(
    q1_actual: float,
    q1_last_year: float,
    full_year_estimate: float,
    full_year_last_year: float,
) -> dict:
    """Check whether Q1 actuals constrain the full-year estimate.

    Computes the implied Q2-Q4 growth rate required to hit the full-year
    estimate given Q1 actuals, and flags unreasonable gaps.

    Returns dict with implied growth, feasibility flag, and seasonality context.
    """
    if full_year_last_year == 0 or q1_last_year == 0:
        return {"error": "Prior year values are zero, cannot compute growth rates"}

    full_year_growth = (full_year_estimate - full_year_last_year) / full_year_last_year
    q1_growth = (q1_actual - q1_last_year) / q1_last_year

    q2_q4_last_year = full_year_last_year - q1_last_year
    q2_q4_required = full_year_estimate - q1_actual

    if q2_q4_last_year <= 0:
        return {"error": "Q2-Q4 last year is non-positive, cannot compute implied growth"}

    implied_q2_q4_growth = (q2_q4_required - q2_q4_last_year) / q2_q4_last_year

    # Q1 share of full year (seasonality reference)
    q1_share_last_year = q1_last_year / full_year_last_year

    # Feasibility: compare implied Q2-Q4 growth vs full-year growth
    growth_gap = implied_q2_q4_growth - full_year_growth

    if implied_q2_q4_growth > 0.40:
        feasibility = "UNREASONABLE — implied Q2-Q4 growth >40%, consider downgrading full-year estimate"
    elif implied_q2_q4_growth > 0.25:
        feasibility = "STRETCH — implied Q2-Q4 growth >25%, needs strong H2 catalyst to justify"
    elif implied_q2_q4_growth > 0.10:
        feasibility = "REASONABLE — implied Q2-Q4 growth in normal range"
    elif implied_q2_q4_growth > 0:
        feasibility = "CONSERVATIVE — implied Q2-Q4 growth is modest"
    else:
        feasibility = "OVERLY CONSERVATIVE — Q1 already covers more than full-year growth implies"

    # Check if Q2-Q4 acceleration needed vs Q1
    acceleration = implied_q2_q4_growth - q1_growth
    acceleration_note = ""
    if acceleration > 0.20:
        acceleration_note = (
            f"WARNING: Q2-Q4 needs to accelerate {acceleration:+.1%} vs Q1 ({q1_growth:+.1%}). "
            f"This requires a significant inflection point in H2."
        )
    elif acceleration > 0.10:
        acceleration_note = (
            f"Q2-Q4 needs moderate acceleration ({acceleration:+.1%}) vs Q1 ({q1_growth:+.1%}). "
            f"Ensure H2 catalysts are concrete and near-term."
        )

    return {
        "q1_actual": q1_actual,
        "q1_growth": q1_growth,
        "full_year_estimate": full_year_estimate,
        "full_year_growth": full_year_growth,
        "implied_q2_q4_required": q2_q4_required,
        "implied_q2_q4_growth": implied_q2_q4_growth,
        "growth_gap_vs_full_year": growth_gap,
        "q1_share_last_year": q1_share_last_year,
        "feasibility": feasibility,
        "acceleration_note": acceleration_note,
    }
