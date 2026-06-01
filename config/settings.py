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

# ── Cache ────────────────────────────────────────────────────────
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "24"))
