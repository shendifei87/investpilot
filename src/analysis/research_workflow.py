"""Sequential research workflow guard.

InvestPilot's research steps are dependency-ordered.  This module persists a
small state machine so agents cannot advance Step 2-7 in parallel or skip ahead
without completed prerequisites.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.analysis._base import WorkspaceStateBase


STEP_FILES = {
    0: "step0_quick_triage.md",
    1: "step1_business_analysis.md",
    2: "step2_competitive_moat.md",
    3: "step3_marginal_changes.md",
    4: "step4_quantitative_model.md",
    5: "step5_rrr_strategy.md",
    6: "step6_auditing.md",
    7: "step7_research_director_review.md",
}

STEP_DEPENDENCIES = {
    0: [],
    1: [],
    2: [1],
    3: [1, 2],
    4: [1, 2, 3],
    5: [1, 2, 3, 4],
    6: [1, 2, 3, 4, 5],
    7: [1, 2, 3, 4, 5, 6],
}

VALID_STATUSES = {"not_started", "in_progress", "completed", "blocked", "skipped"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ResearchWorkflow(WorkspaceStateBase):
    """Persist and enforce sequential Step 0-7 research state."""

    _state_file = "research_workflow.json"
    _default_state = {
        "version": 1,
        "steps": {str(i): {"status": "not_started"} for i in range(8)},
        "history": [],
    }

    def _step(self, step: int) -> dict:
        if step not in STEP_FILES:
            raise ValueError(f"Invalid step: {step}. Expected 0-7.")
        steps = self._data.setdefault("steps", {})
        return steps.setdefault(str(step), {"status": "not_started"})

    def _status(self, step: int) -> str:
        return self._step(step).get("status", "not_started")

    def _record(self, action: str, step: int, detail: str = ""):
        self._data.setdefault("history", []).append({
            "at": _now(),
            "action": action,
            "step": step,
            "detail": detail,
        })

    def sync_from_files(self) -> dict:
        """Mark existing step files as completed when prerequisites are present.

        This supports old workspaces while preserving the sequential guard:
        a stray Step 4 file should not make Step 4 completed unless Step 1-3
        are already completed or also present and synced earlier in order.
        """
        for step, filename in STEP_FILES.items():
            current = self._status(step)
            if current in {"completed", "blocked", "skipped"}:
                continue
            deps_completed = all(self._status(dep) == "completed" for dep in STEP_DEPENDENCIES[step])
            if not deps_completed:
                continue
            if (self.workspace / filename).exists():
                rec = self._step(step)
                rec["status"] = "completed"
                rec["completed_at"] = rec.get("completed_at") or _now()
                rec["artifact"] = filename
        self._save()
        return self.snapshot()

    def can_start(self, step: int) -> dict:
        """Return whether the requested step can start now."""
        if step not in STEP_FILES:
            return {"allowed": False, "reason": f"Invalid step: {step}"}

        active = [
            s for s in range(8)
            if s != step and self._status(s) == "in_progress"
        ]
        if active:
            return {
                "allowed": False,
                "reason": f"Step {active[0]} is already in progress. Finish or block it before starting Step {step}.",
                "active_step": active[0],
            }

        missing = [
            dep for dep in STEP_DEPENDENCIES[step]
            if self._status(dep) != "completed"
        ]
        if missing:
            return {
                "allowed": False,
                "reason": f"Step {step} prerequisites not completed: {missing}",
                "missing_dependencies": missing,
            }

        status = self._status(step)
        if status == "completed":
            return {
                "allowed": False,
                "reason": f"Step {step} is already completed. Use --force to reopen intentionally.",
            }
        if status == "blocked":
            return {
                "allowed": False,
                "reason": f"Step {step} is blocked. Resolve blocker or use --force intentionally.",
            }
        return {"allowed": True, "reason": "OK"}

    def start_step(self, step: int, force: bool = False) -> dict:
        guard = self.can_start(step)
        if not guard["allowed"] and not force:
            return {"started": False, **guard}
        rec = self._step(step)
        rec["status"] = "in_progress"
        rec["started_at"] = _now()
        rec.pop("blocked_at", None)
        self._record("start", step, "force" if force else "")
        self._save()
        return {"started": True, "step": step, "status": "in_progress", "forced": force}

    def complete_step(
        self,
        step: int,
        artifact: str | None = None,
        validation_summary: str = "",
        force: bool = False,
    ) -> dict:
        rec = self._step(step)
        if rec.get("status") != "in_progress" and not force:
            return {
                "completed": False,
                "reason": f"Step {step} is not in progress. Start it before marking completed.",
            }
        artifact = artifact or STEP_FILES[step]
        if artifact and not (self.workspace / artifact).exists() and not force:
            return {
                "completed": False,
                "reason": f"Artifact not found for Step {step}: {artifact}",
            }
        rec["status"] = "completed"
        rec["completed_at"] = _now()
        rec["artifact"] = artifact
        rec["validation_summary"] = validation_summary
        self._record("complete", step, validation_summary)
        self._save()
        return {"completed": True, "step": step, "status": "completed"}

    def block_step(self, step: int, reason: str) -> dict:
        rec = self._step(step)
        rec["status"] = "blocked"
        rec["blocked_at"] = _now()
        rec["block_reason"] = reason
        self._record("block", step, reason)
        self._save()
        return {"blocked": True, "step": step, "reason": reason}

    def next_step(self) -> dict:
        """Return the earliest actionable Step 1-7.

        Step 0 (quick triage) is optional and excluded from next_step
        progression — agents decide independently whether to run it.
        """
        for step in range(1, 8):
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
