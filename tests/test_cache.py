"""Tests for the TTL-based data cache (src/data/cache.py)."""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestFetchAndCache:
    """Tests for fetch_and_cache()."""

    def test_caches_fresh_data(self, tmp_path):
        import src.data.cache as cache_mod

        # Patch CACHE_DIR to use tmp_path
        with patch.object(cache_mod, "CACHE_DIR", tmp_path):
            df = pd.DataFrame({"close": [100, 101, 102]})
            call_count = {"n": 0}

            def fetch():
                call_count["n"] += 1
                return df

            result = cache_mod.fetch_and_cache("test_key", fetch, ttl_hours=24)
            assert call_count["n"] == 1
            assert len(result) == 3
            assert (tmp_path / "test_key.csv").exists()
            assert (tmp_path / "test_key.meta.json").exists()

    def test_returns_cached_within_ttl(self, tmp_path):
        import src.data.cache as cache_mod

        with patch.object(cache_mod, "CACHE_DIR", tmp_path):
            # Pre-populate cache
            df = pd.DataFrame({"close": [200, 201]})
            df.to_csv(tmp_path / "cached_key.csv")
            meta = {"timestamp": time.time(), "key": "cached_key"}
            (tmp_path / "cached_key.meta.json").write_text(json.dumps(meta))

            call_count = {"n": 0}

            def fetch():
                call_count["n"] += 1
                return pd.DataFrame({"close": [999]})

            result = cache_mod.fetch_and_cache("cached_key", fetch, ttl_hours=24)
            assert call_count["n"] == 0  # Should NOT call fetch
            assert result["close"].iloc[0] == 200  # Returns cached data

    def test_refetches_after_ttl_expired(self, tmp_path):
        import src.data.cache as cache_mod

        with patch.object(cache_mod, "CACHE_DIR", tmp_path):
            # Pre-populate with expired cache (1 hour ago, TTL=0)
            df = pd.DataFrame({"close": [200]})
            df.to_csv(tmp_path / "expired_key.csv")
            meta = {"timestamp": time.time() - 3600, "key": "expired_key"}
            (tmp_path / "expired_key.meta.json").write_text(json.dumps(meta))

            def fetch():
                return pd.DataFrame({"close": [300]})

            result = cache_mod.fetch_and_cache("expired_key", fetch, ttl_hours=0)
            assert result["close"].iloc[0] == 300

    def test_raises_on_none_return(self, tmp_path):
        import src.data.cache as cache_mod

        with patch.object(cache_mod, "CACHE_DIR", tmp_path):
            with pytest.raises(ValueError, match="returned None"):
                cache_mod.fetch_and_cache("bad_key", lambda: None)

    def test_handles_meta_missing(self, tmp_path):
        """If CSV exists but meta.json missing, should refetch."""
        import src.data.cache as cache_mod

        with patch.object(cache_mod, "CACHE_DIR", tmp_path):
            df = pd.DataFrame({"close": [50]})
            df.to_csv(tmp_path / "no_meta.csv")
            # No meta.json

            def fetch():
                return pd.DataFrame({"close": [60]})

            result = cache_mod.fetch_and_cache("no_meta", fetch, ttl_hours=24)
            assert result["close"].iloc[0] == 60

    def test_handles_corrupt_meta_as_cache_miss(self, tmp_path):
        import src.data.cache as cache_mod

        with patch.object(cache_mod, "CACHE_DIR", tmp_path):
            pd.DataFrame({"close": [50]}).to_csv(tmp_path / "bad_meta.csv")
            (tmp_path / "bad_meta.meta.json").write_text("{bad json", encoding="utf-8")

            result = cache_mod.fetch_and_cache(
                "bad_meta",
                lambda: pd.DataFrame({"close": [70]}),
                ttl_hours=24,
            )

            assert result["close"].iloc[0] == 70


class TestInvalidateCache:
    """Tests for invalidate_cache()."""

    def test_invalidates_by_ticker(self, tmp_path):
        import src.data.cache as cache_mod

        with patch.object(cache_mod, "CACHE_DIR", tmp_path):
            # Create some cache files
            (tmp_path / "600519_price.csv").write_text("data")
            (tmp_path / "600519_price.meta.json").write_text("{}")
            (tmp_path / "other_data.csv").write_text("data")

            cache_mod.invalidate_cache("600519")
            assert not (tmp_path / "600519_price.csv").exists()
            assert not (tmp_path / "600519_price.meta.json").exists()
            assert (tmp_path / "other_data.csv").exists()  # Untouched

    def test_noop_when_cache_dir_missing(self, tmp_path):
        import src.data.cache as cache_mod

        nonexistent = tmp_path / "no_such_dir"
        with patch.object(cache_mod, "CACHE_DIR", nonexistent):
            # Should not raise
            cache_mod.invalidate_cache("anything")


class TestClearAllCache:
    """Tests for clear_all_cache()."""

    def test_clears_all_files(self, tmp_path):
        import src.data.cache as cache_mod

        with patch.object(cache_mod, "CACHE_DIR", tmp_path):
            (tmp_path / "a.csv").write_text("data")
            (tmp_path / "b.meta.json").write_text("{}")
            (tmp_path / "subdir").mkdir()  # Should not delete dirs

            cache_mod.clear_all_cache()
            assert not (tmp_path / "a.csv").exists()
            assert not (tmp_path / "b.meta.json").exists()
            assert (tmp_path / "subdir").exists()  # Dir preserved
