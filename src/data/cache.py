import json
import time
from pathlib import Path
from typing import Callable

import pandas as pd

from config.settings import CACHE_DIR


def _cache_path(cache_key: str) -> Path:
    return CACHE_DIR / f"{cache_key}.csv"


def _meta_path(cache_key: str) -> Path:
    return CACHE_DIR / f"{cache_key}.meta.json"


def fetch_and_cache(
    cache_key: str,
    fetch_fn: Callable[[], pd.DataFrame],
    ttl_hours: int = 24,
) -> pd.DataFrame:
    cp = _cache_path(cache_key)
    mp = _meta_path(cache_key)

    if cp.exists() and mp.exists():
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
            age_hours = (time.time() - meta["timestamp"]) / 3600
            if age_hours < ttl_hours:
                return pd.read_csv(cp, index_col=0)
        except (json.JSONDecodeError, KeyError, OSError, ValueError):
            pass

    df = fetch_fn()
    if df is None:
        raise ValueError(f"fetch_fn for '{cache_key}' returned None")
    if df.empty:
        return df
    df.to_csv(cp)
    mp.write_text(json.dumps({"timestamp": time.time(), "key": cache_key}), encoding="utf-8")
    return df


def invalidate_cache(ticker: str) -> None:
    if not CACHE_DIR.exists():
        return
    sep = "_"
    for f in CACHE_DIR.iterdir():
        if not f.is_file():
            continue
        name = f.stem
        # Match exact ticker segment: "daily_600519.SH_..." or "600519.SH_..."
        parts = name.split(sep)
        if ticker in parts:
            f.unlink()


def clear_all_cache() -> None:
    if not CACHE_DIR.exists():
        return
    for f in CACHE_DIR.iterdir():
        if f.is_file():
            f.unlink()
