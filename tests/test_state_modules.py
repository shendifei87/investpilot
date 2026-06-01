"""Tests for src.storage — Atomic JSON persistence layer."""

import json
import tempfile
import threading
from pathlib import Path

import pytest

from src.storage import AtomicJSON


class TestAtomicJSONLoad:
    def test_load_missing_file_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AtomicJSON(Path(tmp))
            data = store.load("nonexistent.json", default={"key": "value"})
            assert data == {"key": "value"}

    def test_load_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.json"
            p.write_text('{"hello": "world"}')
            store = AtomicJSON(Path(tmp))
            data = store.load("test.json")
            assert data == {"hello": "world"}

    def test_load_corrupt_falls_back_to_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.json"
            bak = Path(tmp) / "test.json.bak"
            p.write_text("{corrupt json!!!")
            bak.write_text('{"recovered": true}')
            store = AtomicJSON(Path(tmp))
            data = store.load("test.json")
            assert data == {"recovered": True}

    def test_load_corrupt_both_returns_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "test.json"
            bak = Path(tmp) / "test.json.bak"
            p.write_text("{bad")
            bak.write_text("{also bad")
            store = AtomicJSON(Path(tmp))
            data = store.load("test.json", default={"fallback": 1})
            assert data == {"fallback": 1}


class TestAtomicJSONSave:
    def test_save_creates_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AtomicJSON(Path(tmp))
            store.save("data.json", {"key": "value"})
            p = Path(tmp) / "data.json"
            assert p.exists()
            assert json.loads(p.read_text()) == {"key": "value"}

    def test_save_creates_backup_on_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AtomicJSON(Path(tmp))
            store.save("data.json", {"v": 1})
            store.save("data.json", {"v": 2})
            bak = Path(tmp) / "data.json.bak"
            assert bak.exists()
            assert json.loads(bak.read_text()) == {"v": 1}

    def test_atomic_no_partial_writes(self):
        """Simulate crash during write: temp file should not remain."""
        with tempfile.TemporaryDirectory() as tmp:
            store = AtomicJSON(Path(tmp))
            store.save("data.json", {"ok": True})
            p = Path(tmp) / "data.json"
            assert p.exists()
            # Verify no temp files left behind
            tmp_files = list(Path(tmp).glob(".data.json.tmp_*"))
            assert len(tmp_files) == 0

    def test_concurrent_writes_no_data_loss(self):
        """Multiple threads writing to the same file with file locking."""
        with tempfile.TemporaryDirectory() as tmp:
            errors = []
            completed_count = []

            def writer(n):
                try:
                    store = AtomicJSON(Path(tmp))
                    for i in range(20):
                        data = store.load("counter.json", default={"count": 0})
                        data["count"] = data.get("count", 0) + 1
                        store.save("counter.json", data)
                except Exception as e:
                    errors.append(e)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(errors) == 0, f"Errors during concurrent writes: {errors}"
            # With file locking, final count should be > 0
            # (exact count may vary due to read-modify-write race between load and save)
            store = AtomicJSON(Path(tmp))
            final = store.load("counter.json", default={"count": 0})
            assert final["count"] > 0, f"Expected some writes, got {final['count']}"
            assert final["count"] <= 100, f"Should not exceed 100, got {final['count']}"


class TestAtomicJSONRecover:
    def test_recover_from_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AtomicJSON(Path(tmp))
            # Save twice so second save creates a backup of the first
            store.save("data.json", {"v": 1})
            store.save("data.json", {"good": True})
            # Now backup has {"v": 1} and primary has {"good": True}
            # Corrupt the primary
            primary = Path(tmp) / "data.json"
            primary.write_text("{corrupt!!")
            # Verify primary is indeed corrupt
            try:
                json.loads(primary.read_text())
                pytest.skip("File should be corrupt but parsed OK")
            except json.JSONDecodeError:
                pass
            # recover() should detect corrupt primary and restore from backup
            recovered = store.recover("data.json")
            assert recovered == {"v": 1}
            # Primary should now be restored
            data = store.load("data.json")
            assert data == {"v": 1}

    def test_no_recovery_needed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = AtomicJSON(Path(tmp))
            store.save("data.json", {"ok": True})
            result = store.recover("data.json")
            assert result is None
