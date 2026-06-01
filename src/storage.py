"""Atomic JSON persistence layer for InvestPilot state modules.

Provides thread-safe, crash-safe JSON file operations:
- Atomic writes via temp file + os.replace
- File locking via fcntl (Unix/macOS)
- Write-before-backup for recovery
- Corruption detection with fallback to backup

Usage:
    from src.storage import AtomicJSON

    store = AtomicJSON(Path("workspaces/600584.SH"))
    data = store.load("thesis.json", default={"version": 1, "history": []})
    data["history"].append(revision)
    store.save("thesis.json", data)
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import tempfile
from pathlib import Path


class AtomicJSON:
    """Atomic, locked JSON file operations for a workspace directory."""

    def __init__(self, workspace_dir: Path):
        self._dir = Path(workspace_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock_file = self._dir / ".storage.lock"

    def load(self, filename: str, default: dict | list | None = None) -> dict | list:
        """Load JSON file with corruption recovery.

        Tries: primary file → backup file → default value.
        """
        filepath = self._dir / filename
        backup = self._dir / f"{filename}.bak"

        for path in [filepath, backup]:
            if path.exists():
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return data
                except (json.JSONDecodeError, ValueError, OSError):
                    continue

        if default is not None:
            return default

        # Return sensible defaults for common patterns
        if filename == "thesis.json":
            return {"version": 1, "history": []}
        elif filename == "catalysts.json":
            return {"version": 1, "catalysts": [], "kill_switches": []}
        elif filename == "edge_score.json":
            return []
        return {}

    def save(self, filename: str, data: dict | list) -> Path:
        """Atomically write JSON data.

        Steps:
        1. Acquire file lock
        2. Backup existing file (if any)
        3. Write to temp file in same directory
        4. Atomic rename (os.replace) to final path
        5. Release lock
        """
        filepath = self._dir / filename
        backup = self._dir / f"{filename}.bak"

        lock_fd = self._lock_file.open("w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)

            # Backup existing file before overwrite
            if filepath.exists():
                try:
                    shutil.copy2(filepath, backup)
                except OSError:
                    pass  # Best-effort backup

            # Write to temp file in same directory (same filesystem for atomic rename)
            content = json.dumps(data, ensure_ascii=False, indent=2)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._dir), prefix=f".{filename}.tmp_", suffix=".json"
            )
            try:
                os.write(fd, content.encode("utf-8"))
                os.close(fd)
                os.replace(tmp_path, str(filepath))
            except BaseException:
                # Clean up temp file on any failure
                try:
                    os.close(fd)
                except OSError:
                    pass
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            return filepath
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

    def recover(self, filename: str) -> dict | list | None:
        """Attempt recovery from backup if primary is corrupt.

        Returns recovered data or None if no recovery possible.
        """
        filepath = self._dir / filename
        backup = self._dir / f"{filename}.bak"

        # Check if primary is OK
        if filepath.exists():
            try:
                json.loads(filepath.read_text(encoding="utf-8"))
                return None  # Primary is fine
            except (json.JSONDecodeError, ValueError):
                pass

        # Primary is corrupt or missing. Try backup.
        if not backup.exists():
            return None

        try:
            data = json.loads(backup.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, ValueError):
            return None

        # Restore backup as primary using direct write (not self.save
        # which would try to re-backup the corrupt primary)
        lock_fd = self._lock_file.open("w")
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
            content = json.dumps(data, ensure_ascii=False, indent=2)
            fd, tmp_path = tempfile.mkstemp(
                dir=str(self._dir), prefix=f".{filename}.tmp_", suffix=".json"
            )
            try:
                os.write(fd, content.encode("utf-8"))
                os.close(fd)
                os.replace(tmp_path, str(filepath))
            except BaseException:
                try:
                    os.close(fd)
                except OSError:
                    pass
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()

        return data
