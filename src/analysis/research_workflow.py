"""Sequential research workflow guard.

InvestPilot's research steps are dependency-ordered. This module persists a
small state machine so agents cannot advance Step 2-9 in parallel or skip ahead
without completed prerequisites.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from src.analysis._base import WorkspaceStateBase
from src.contracts import (
    STEP_DEPENDENCIES,
    STEP_FILES,
    STEP_ORDER,
    artifact_contract_status,
    get_step_contract,
    normalize_step_id,
)


def _clear_guard_artifacts(workspace: Path, step_id: int | str) -> None:
    """Remove stale guard artifacts when restarting a step.

    This prevents stale blocker files and guard state from blocking
    a fresh attempt after the underlying issues have been fixed.
    """
    artifacts = [
        workspace / f"step{step_id}_blockers.md",
        workspace / f"step{step_id}_guard_state.json",
    ]
    # Also clean the step4-specific guard that step5 model builder checks
    if str(step_id) in {"4", "5"}:
        artifacts.append(workspace / "step4_blockers.md")
        artifacts.append(workspace / "step4_guard_state.json")
    for path in artifacts:
        try:
            if path.exists():
                os.remove(path)
        except OSError:
            pass

VALID_STATUSES = {"not_started", "in_progress", "completed", "blocked", "skipped"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ResearchWorkflow(WorkspaceStateBase):
    """Persist and enforce sequential research state."""

    _state_file = "research_workflow.json"
    _default_state = {
        "version": 3,
        "steps": {step: {"status": "not_started"} for step in STEP_ORDER},
        "history": [],
    }

    def __init__(self, workspace_dir: str):
        super().__init__(workspace_dir)
        if self._cleanup_removed_steps():
            self._save()

    def _cleanup_removed_steps(self) -> bool:
        """Drop obsolete split-step state and ensure current keys exist."""
        changed = False
        steps = self._data.setdefault("steps", {})

        previous_version = int(self._data.get("version", 1) or 1)
        obsolete = {"4a", "4b", "4c"}
        if previous_version < 3:
            obsolete.update({"4", "5", "6", "7"})
        for step in obsolete:
            if step in steps:
                steps.pop(step, None)
                changed = True

        for step in STEP_ORDER:
            if step not in steps:
                steps[step] = {"status": "not_started"}
                changed = True

        self._data["version"] = 3
        return changed

    def _step(self, step: int | str) -> dict:
        step_id = normalize_step_id(step)
        steps = self._data.setdefault("steps", {})
        return steps.setdefault(step_id, {"status": "not_started"})

    def _status(self, step: int | str) -> str:
        return self._step(step).get("status", "not_started")

    def _record(self, action: str, step: int | str, detail: str = ""):
        step_id = normalize_step_id(step)
        self._data.setdefault("history", []).append({
            "at": _now(),
            "action": action,
            "step": step_id,
            "detail": detail,
        })

    def sync_from_files(self) -> dict:
        """Mark existing step files as completed when prerequisites are present.

        This supports syncing canonical split-step artifacts while preserving
        the sequential guard.
        """
        for step in STEP_ORDER:
            current = self._status(step)
            if current in {"completed", "blocked", "skipped"}:
                continue
            deps_completed = all(self._status(dep) == "completed" for dep in STEP_DEPENDENCIES[step])
            if not deps_completed:
                continue
            artifact_status = artifact_contract_status(self.workspace, step)
            if artifact_status["passed"]:
                filename = STEP_FILES[step]
                rec = self._step(step)
                rec["status"] = "completed"
                rec["completed_at"] = rec.get("completed_at") or _now()
                rec["artifact"] = filename
                rec["artifact_contract"] = artifact_status
        self._save()
        return self.snapshot()

    def can_start(self, step: int | str) -> dict:
        """Return whether the requested step can start now."""
        try:
            step_id = normalize_step_id(step)
        except ValueError as e:
            return {"allowed": False, "reason": str(e)}

        active = [
            s for s in STEP_ORDER
            if s != step_id and self._status(s) == "in_progress"
        ]
        if active:
            return {
                "allowed": False,
                "reason": f"Step {active[0]} is already in progress. Finish or block it before starting Step {step_id}.",
                "active_step": active[0],
            }

        missing = [
            dep for dep in STEP_DEPENDENCIES[step_id]
            if self._status(dep) != "completed"
        ]
        if missing:
            return {
                "allowed": False,
                "reason": f"Step {step_id} prerequisites not completed: {missing}",
                "missing_dependencies": missing,
            }

        status = self._status(step_id)
        if status == "completed":
            return {
                "allowed": False,
                "reason": f"Step {step_id} is already completed. Use --force to reopen intentionally.",
            }
        if status == "blocked":
            return {
                "allowed": False,
                "reason": f"Step {step_id} is blocked. Resolve blocker or use --force intentionally.",
            }
        return {"allowed": True, "reason": "OK"}

    def start_step(self, step: int | str, force: bool = False) -> dict:
        try:
            step_id = normalize_step_id(step)
        except ValueError as e:
            return {"started": False, "allowed": False, "reason": str(e)}
        guard = self.can_start(step_id)
        if not guard["allowed"] and not force:
            return {"started": False, **guard}
        rec = self._step(step_id)
        rec["status"] = "in_progress"
        rec["started_at"] = _now()
        rec.pop("blocked_at", None)
        rec.pop("block_reason", None)
        # ── Clear stale guard artifacts ──
        _clear_guard_artifacts(self.workspace, step_id)
        self._record("start", step_id, "force" if force else "")
        self._save()
        return {"started": True, "step": step_id, "status": "in_progress", "forced": force}

    def complete_step(
        self,
        step: int | str,
        artifact: str | None = None,
        validation_summary: str = "",
        force: bool = False,
    ) -> dict:
        try:
            step_id = normalize_step_id(step)
        except ValueError as e:
            return {"completed": False, "allowed": False, "reason": str(e)}
        rec = self._step(step_id)
        if rec.get("status") != "in_progress" and not force:
            return {
                "completed": False,
                "reason": f"Step {step_id} is not in progress. Start it before marking completed.",
            }
        contract = get_step_contract(step_id)
        artifact = artifact or contract.primary_artifact
        artifact_status = artifact_contract_status(self.workspace, step_id)
        if not artifact_status["passed"] and not force:
            return {
                "completed": False,
                "reason": (
                    f"Artifact contract failed for Step {step_id}. "
                    f"Missing required: {artifact_status['missing_required']}; "
                    f"forbidden present: {artifact_status['forbidden_present']}"
                ),
                "artifact_contract": artifact_status,
            }
        if artifact and not (self.workspace / artifact).exists() and not force:
            return {
                "completed": False,
                "reason": f"Artifact not found for Step {step_id}: {artifact}",
            }
        rec["status"] = "completed"
        rec["completed_at"] = _now()
        rec["artifact"] = artifact
        rec["artifact_contract"] = artifact_status
        rec["validation_summary"] = validation_summary
        self._record("complete", step_id, validation_summary)
        self._save()
        return {"completed": True, "step": step_id, "status": "completed"}

    def block_step(self, step: int | str, reason: str) -> dict:
        try:
            step_id = normalize_step_id(step)
        except ValueError as e:
            return {"blocked": False, "allowed": False, "reason": str(e)}
        rec = self._step(step_id)
        rec["status"] = "blocked"
        rec["blocked_at"] = _now()
        rec["block_reason"] = reason
        self._record("block", step_id, reason)
        self._save()
        return {"blocked": True, "step": step_id, "reason": reason}

    def next_step(self) -> dict:
        """Return the earliest actionable Step 1-9.

        Step 0 (quick triage) is optional and excluded from next_step
        progression — agents decide independently whether to run it.
        """
        for step in STEP_ORDER[1:]:
            if self._status(step) in {"not_started", "in_progress", "blocked"}:
                return {"step": step, "status": self._status(step), "guard": self.can_start(step)}
        return {"step": None, "status": "complete", "guard": {"allowed": False, "reason": "All steps completed"}}

    def snapshot(self) -> dict:
        return {
            "workspace": self.workspace.name,
            "steps": self._data.get("steps", {}),
            "next": self.next_step(),
            "history": self._data.get("history", []),
        }
