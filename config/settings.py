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

# ── Environment helpers ──────────────────────────────────────────
def _read_dotenv_value(key: str) -> str:
    """Read KEY from a simple project-level .env file without extra deps.

    Handles values containing ``=`` (e.g. TOKEN=abc=def) by splitting only
    on the first ``=`` and stripping surrounding quotes.
    """
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return ""
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() != key:
                continue
            v = v.strip()
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            return v
    except OSError:
        return ""
    return ""


def get_env_value(key: str, default: str = "") -> str:
    """Read env dynamically, falling back to project .env.

    Some CLI/web sessions import config before the shell env is updated; callers
    that need fresh credentials should call this function instead of relying
    only on import-time constants.
    """
    return os.getenv(key, "") or _read_dotenv_value(key) or default


# ── Tushare ──────────────────────────────────────────────────────
TUSHARE_TOKEN = get_env_value("TUSHARE_TOKEN", "")


def get_tushare_token() -> str:
    return get_env_value("TUSHARE_TOKEN", TUSHARE_TOKEN)

# ── Monte Carlo ──────────────────────────────────────────────────
MONTE_CARLO_SIMULATIONS = int(os.getenv("MC_SIMS", "100000"))

# ── Cache ────────────────────────────────────────────────────────
CACHE_TTL_HOURS = int(os.getenv("CACHE_TTL_HOURS", "24"))
