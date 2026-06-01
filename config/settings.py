import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = PROJECT_ROOT / "reports"
CACHE_DIR = PROJECT_ROOT / "data_cache"
WORKSPACES_DIR = PROJECT_ROOT / "workspaces"
PROMPTS_DIR = PROJECT_ROOT / "prompts"

for d in [REPORTS_DIR, CACHE_DIR, WORKSPACES_DIR]:
    d.mkdir(parents=True, exist_ok=True)

MARKET_CONFIG = {
    "US": {
        "exchange": "NYSE / NASDAQ",
        "currency": "USD",
        "suffix": "",
        "primary_source": "tushare",
    },
    "HK": {
        "exchange": "HKEX",
        "currency": "HKD",
        "suffix": ".HK",
        "primary_source": "tushare",
    },
    "ASHARE": {
        "exchange": "SSE / SZSE",
        "currency": "CNY",
        "suffix": "",
        "primary_source": "tushare",
    },
}

# ── Tushare ──────────────────────────────────────────────────────
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")

# ── Monte Carlo ──────────────────────────────────────────────────
MONTE_CARLO_SIMULATIONS = int(os.getenv("MC_SIMS", "100000"))

# ── EQC (Earnings Quality) weights ──────────────────────────────
EQC_WEIGHTS = {
    "cash_conversion": 0.30,
    "accrual_ratio": 0.25,
    "receivables_trend": 0.20,
    "margin_consistency": 0.15,
    "revenue_quality": 0.10,
}

# ── Edge Scorer weights ─────────────────────────────────────────
EDGE_WEIGHTS = {
    "analytical": 0.35,
    "temporal": 0.25,
    "informational": 0.20,
    "structural": 0.20,
}

# ── RRR thresholds ───────────────────────────────────────────────
RRR_THRESHOLDS = {
    "strong": 2.0,   # >2.0 → build position
    "watch": 1.0,    # 1.0-2.0 → wait for catalyst
    "avoid": 1.0,    # <1.0 → don't trade
}

# ── Time decay curve (days, conviction_modifier) ────────────────
TIME_DECAY_CURVE = [
    (0, 30, 1.0),       # fresh: 0-30 days
    (30, 60, 0.85),     # early_decay: 30-60 days
    (60, 90, 0.65),     # active_decay: 60-90 days
    (90, None, 0.40),   # expired_zone: 90+ days (floor)
]

# ── DCF defaults ─────────────────────────────────────────────────
DCF_DEFAULTS = {
    "terminal_growth": 0.03,
    "years": 5,
    "wacc": 0.08,
}

# ── Valuation ────────────────────────────────────────────────────
PE_BAND_WINDOW_WEEKS = 260  # 5 years
PE_BAND_PERCENTILES = [10, 25, 50, 75, 90]

# ── Cache ────────────────────────────────────────────────────────
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "24"))
CACHE_MAX_SIZE_MB = int(os.getenv("CACHE_MAX_SIZE_MB", "500"))

# ── Data fetcher ─────────────────────────────────────────────────
FETCH_RETRY_ATTEMPTS = 3
FETCH_RETRY_BACKOFF_BASE = 1.0  # seconds
FETCH_RATE_LIMIT_DELAY = (0.5, 1.5)  # min/max seconds between API calls
