"""Sequential research workflow guard.

InvestPilot's research steps are dependency-ordered. This module persists a
small state machine so agents cannot advance Step 2-9 in parallel or skip ahead
without completed prerequisites.
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)


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

        int(self._data.get("version", 1) or 1)
        obsolete = {"4a", "4b", "4c"}
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
            if current in {"completed", "blocked", "skipped", "in_progress"}:
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
        if force:
            rec["forced_start"] = {
                "at": _now(),
                "guard": guard,
            }
        # ── Clear stale guard artifacts ──
        _clear_guard_artifacts(self.workspace, step_id)
        self._record("start", step_id, f"force: {guard.get('reason', 'OK')}" if force else "")
        self._save()
        return {
            "started": True,
            "step": step_id,
            "status": "in_progress",
            "forced": force,
            "guard": guard,
        }

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
                    f"invalid required: {artifact_status['invalid_required']}; "
                    f"forbidden present: {artifact_status['forbidden_present']}"
                ),
                "artifact_contract": artifact_status,
            }
        if artifact and not (self.workspace / artifact).exists() and not force:
            return {
                "completed": False,
                "reason": f"Artifact not found for Step {step_id}: {artifact}",
            }
        semantic_gate = self._run_semantic_gate(step_id) if not force else {
            "passed": True,
            "step": step_id,
            "summary": "semantic validation skipped by force",
        }
        if not semantic_gate.get("passed"):
            return {
                "completed": False,
                "reason": (
                    f"Validation gate failed for Step {step_id}: "
                    f"{semantic_gate.get('summary', 'semantic validation failed')}"
                ),
                "artifact_contract": artifact_status,
                "semantic_gate": semantic_gate,
            }
        rec["status"] = "completed"
        rec["completed_at"] = _now()
        rec["artifact"] = artifact
        rec["artifact_contract"] = artifact_status
        rec["semantic_gate"] = semantic_gate
        rec["validation_summary"] = validation_summary
        if force:
            rec["forced_completion"] = {
                "at": _now(),
                "artifact_contract_passed": bool(artifact_status.get("passed")),
                "semantic_gate": semantic_gate,
            }
        detail = (
            f"force: {validation_summary}; artifact_contract_passed={artifact_status.get('passed')}"
            if force
            else validation_summary
        )
        self._record("complete", step_id, detail)
        self._save()

        # ── Auto-trigger report generation on Step 9 completion ──
        result = {
            "completed": True,
            "step": step_id,
            "status": "completed",
            "forced": force,
            "artifact_contract": artifact_status,
            "semantic_gate": semantic_gate,
        }
        if step_id == "9":
            result["post_research"] = self._auto_generate_reports()

        return result

    def _load_json_artifact(self, filename: str) -> dict:
        path = self.workspace / filename
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"{filename} must contain a JSON object")
        return data

    def _run_semantic_gate(self, step_id: str) -> dict:
        """Run deterministic validators for steps with configured gates."""
        try:
            if step_id == "4":
                from src.analysis.step4_validate import validate_step4_with_guard

                result = validate_step4_with_guard(
                    self.workspace / get_step_contract("4").primary_artifact
                )
                return {
                    "passed": bool(result.get("passed")),
                    "step": step_id,
                    "gate": "step4_validation",
                    "summary": result.get("summary", ""),
                    "details": result,
                }

            if step_id == "5":
                from src.analysis.financial_model import validate_financial_model

                model = self._load_json_artifact("forecast_model.json")
                results = validate_financial_model(model, workspace=self.workspace)
                fails = [item for item in results if item.get("status") == "FAIL"]
                return {
                    "passed": not fails,
                    "step": step_id,
                    "gate": "financial_model_validation",
                    "summary": (
                        "financial model validation passed"
                        if not fails
                        else f"{len(fails)} financial model validation failure(s)"
                    ),
                    "failures": fails,
                    "results": results,
                }

            if step_id == "6":
                from src.analysis.monte_carlo import validate_mc_p50_alignment

                mc = self._load_json_artifact("monte_carlo_results.json")
                model = self._load_json_artifact("forecast_model.json")
                alignment = validate_mc_p50_alignment(mc, model)
                checks = alignment.get("checks", [])
                per_year = mc.get("per_year", {})
                seed_present = mc.get("seed") is not None or (
                    isinstance(per_year, dict)
                    and bool(per_year)
                    and all(
                        isinstance(year, dict) and year.get("seed") is not None
                        for year in per_year.values()
                    )
                )
                issues = []
                if not checks:
                    issues.append("no comparable MC/forecast P50 metrics found")
                if not alignment.get("passed"):
                    issues.append(alignment.get("summary", "MC P50 alignment failed"))
                if not seed_present:
                    issues.append("simulation seed missing")
                return {
                    "passed": not issues,
                    "step": step_id,
                    "gate": "monte_carlo_validation",
                    "summary": "Monte Carlo validation passed" if not issues else "; ".join(issues),
                    "alignment": alignment,
                    "seed_present": seed_present,
                }

            if step_id == "8":
                from src.analysis.step8_audit import audit_step_chain

                audit = audit_step_chain(self.workspace, through_step=8)
                return {
                    "passed": bool(audit.get("passed")),
                    "step": step_id,
                    "gate": "step8_audit",
                    "summary": audit.get("summary", ""),
                    "details": audit,
                }
        except Exception as exc:
            return {
                "passed": False,
                "step": step_id,
                "gate": "semantic_validation",
                "summary": str(exc),
            }

        return {
            "passed": True,
            "step": step_id,
            "summary": "no semantic validation gate configured",
        }

    def _auto_generate_reports(self) -> dict:
        """Generate post-research report after Step 9 completes.

        Runs the built-in report generator (HTML + markdown summary).
        Returns a dict with paths to generated files. Failures are logged
        but do NOT block Step 9 completion.
        """
        reports = {}
        ws_str = str(self.workspace)

        # Built-in report (HTML + markdown) — the only report generator
        try:
            from src.report.generator import generate_report_html
            ticker = self.workspace.name
            path = generate_report_html(ws_str, ticker=ticker, company_name="")
            reports["report"] = str(path)
            self._record("auto_report", "9", f"Report: {path}")
        except Exception as e:
            logger.warning("Auto-report generation failed: %s", e)
            reports["report_error"] = str(e)

        # Markdown summary — non-blocking
        try:
            from src.report.generator import generate_summary_md

            ticker = self.workspace.name
            path = generate_summary_md(ws_str, ticker=ticker, company_name="")
            reports["summary"] = str(path)
            self._record("auto_report", "9", f"Summary MD: {path}")
        except Exception as e:
            logger.warning("Auto-summary generation failed: %s", e)
            reports["summary_error"] = str(e)

        # Verify required artifacts exist
        ticker = self.workspace.name
        today = datetime.now().strftime("%Y%m%d")
        required = [
            f"{ticker}_report_{today}.html",
            f"{ticker}_summary_{today}.md",
        ]
        missing = [f for f in required if not (self.workspace / f).exists()]
        reports["required_artifacts"] = {
            "expected": required,
            "missing": missing,
            "all_present": len(missing) == 0,
        }

        if missing:
            logger.warning(
                "Post-research artifacts missing: %s. "
                "Run manually: python -m src.cli report %s",
                missing, ws_str,
            )

        return reports

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
