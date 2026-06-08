import json
from unittest.mock import patch

import pytest

from src.analysis.research_workflow import ResearchWorkflow, STEP_FILES
from src.contracts import get_step_contract


def _workflow(tmp_path):
    ws_dir = tmp_path / "workspaces" / "TEST"
    ws_dir.mkdir(parents=True, exist_ok=True)
    with patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"):
        return ResearchWorkflow("TEST"), ws_dir


def _workflow_named(tmp_path, name):
    ws_dir = tmp_path / "workspaces" / name
    ws_dir.mkdir(parents=True, exist_ok=True)
    with patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"):
        return ResearchWorkflow(name), ws_dir


def _write_required_artifacts(ws_dir, step):
    for artifact in get_step_contract(step).required_artifacts:
        (ws_dir / artifact).write_text(f"# {artifact}\n", encoding="utf-8")


class TestResearchWorkflow:
    def test_step2_cannot_start_before_step1_completed(self, tmp_path):
        wf, _ = _workflow(tmp_path)
        result = wf.start_step(2)
        assert result["started"] is False
        assert "prerequisites" in result["reason"]

    def test_only_one_step_in_progress(self, tmp_path):
        wf, _ = _workflow_named(tmp_path, "ACTIVE")
        assert wf.start_step(1)["started"] is True
        result = wf.start_step(2)
        assert result["started"] is False
        assert "already in progress" in result["reason"]

    def test_complete_requires_artifact(self, tmp_path):
        wf, _ = _workflow(tmp_path)
        assert wf.start_step(1)["started"] is True
        result = wf.complete_step(1)
        assert result["completed"] is False
        assert "Artifact contract failed" in result["reason"]
        assert "step1_business_analysis.md" in result["artifact_contract"]["missing_required"]

    def test_complete_requires_all_contract_artifacts(self, tmp_path):
        wf, ws = _workflow(tmp_path)
        for n in ("1", "2", "3"):
            _write_required_artifacts(ws, n)
        wf.sync_from_files()
        (ws / STEP_FILES["4"]).write_text("# Step 4\n", encoding="utf-8")
        assert wf.start_step("4")["started"] is True

        result = wf.complete_step("4")

        assert result["completed"] is False
        assert "Artifact contract failed" in result["reason"]
        assert "step4_structured_assumptions.json" in result["artifact_contract"]["missing_required"]

    def test_complete_then_next_step_allowed(self, tmp_path):
        wf, ws = _workflow(tmp_path)
        (ws / "step1_business_analysis.md").write_text("# Step 1\n", encoding="utf-8")
        assert wf.start_step(1)["started"] is True
        assert wf.complete_step(1)["completed"] is True
        assert wf.can_start(2)["allowed"] is True

    def test_sync_from_files_marks_existing_completed(self, tmp_path):
        wf, ws = _workflow(tmp_path)
        (ws / "step1_business_analysis.md").write_text("# Step 1\n", encoding="utf-8")
        snap = wf.sync_from_files()
        assert snap["steps"]["1"]["status"] == "completed"

    def test_sync_from_files_respects_dependencies(self, tmp_path):
        wf, ws = _workflow(tmp_path)
        # Deprecated combined model output must not auto-complete current Steps 4/5/6.
        (ws / "step4_quantitative_model.md").write_text("# Step 4\n", encoding="utf-8")
        snap = wf.sync_from_files()
        # Steps 4/5/6 have dependencies on Steps 1-3 which aren't completed
        assert snap["steps"]["4"]["status"] == "not_started"
        assert snap["steps"]["5"]["status"] == "not_started"
        assert snap["steps"]["6"]["status"] == "not_started"

    def test_steps_4_5_6_are_strictly_serial(self, tmp_path):
        """Steps 4→5→6 must complete in order."""
        wf, ws = _workflow(tmp_path)
        for n in ("1", "2", "3"):
            (ws / STEP_FILES[n]).write_text(f"# Step {n}\n", encoding="utf-8")
        wf.sync_from_files()

        # Step 4 can start (deps: 1, 2, 3 all completed)
        assert wf.can_start("4")["allowed"] is True
        # Step 5 cannot start yet (needs Step 4)
        assert wf.can_start("5")["allowed"] is False
        assert wf.start_step("5")["started"] is False

        # Complete Step 4
        _write_required_artifacts(ws, "4")
        assert wf.start_step("4")["started"] is True
        assert wf.complete_step("4")["completed"] is True
        # Step 5 now allowed, Step 6 still blocked
        assert wf.can_start("5")["allowed"] is True
        assert wf.can_start("6")["allowed"] is False

    def test_start_step5_clears_stale_step4_guard_artifacts(self, tmp_path):
        wf, ws = _workflow(tmp_path)
        for n in ("1", "2", "3", "4"):
            _write_required_artifacts(ws, n)
        (ws / "step4_guard_state.json").write_text("{}", encoding="utf-8")
        (ws / "step4_blockers.md").write_text("# stale blocker\n", encoding="utf-8")
        wf.sync_from_files()

        assert wf.start_step("5")["started"] is True

        assert not (ws / "step4_guard_state.json").exists()
        assert not (ws / "step4_blockers.md").exists()

    def test_step_7_requires_4_5_6(self, tmp_path):
        """Step 7 (RRR) cannot start until Steps 4, 5, 6 are all done."""
        wf, ws = _workflow(tmp_path)
        for n in ("1", "2", "3"):
            (ws / STEP_FILES[n]).write_text(f"# Step {n}\n", encoding="utf-8")
        wf.sync_from_files()

        result = wf.can_start("7")
        assert result["allowed"] is False
        assert "4" in str(result["missing_dependencies"])

    def test_deprecated_combined_step4_is_ignored(self, tmp_path):
        """Deprecated step4_quantitative_model.md never satisfies current Steps 4/5/6."""
        wf, ws = _workflow(tmp_path)
        for n in ("1", "2", "3"):
            (ws / STEP_FILES[n]).write_text(f"# Step {n}\n", encoding="utf-8")
        (ws / "step4_quantitative_model.md").write_text("# Deprecated Step 4\n", encoding="utf-8")

        # Only canonical files trigger completion.
        snap = wf.sync_from_files()
        assert snap["steps"]["4"]["status"] == "not_started"
        assert snap["steps"]["5"]["status"] == "not_started"
        assert snap["steps"]["6"]["status"] == "not_started"

    def test_obsolete_in_progress_step4_migrated(self, tmp_path):
        """Old v1 state with step 4 in_progress should be cleaned up."""
        ws = tmp_path / "workspaces" / "LEGACY"
        ws.mkdir(parents=True, exist_ok=True)
        (ws / "research_workflow.json").write_text(json.dumps({
            "version": 1,
            "steps": {
                "1": {"status": "completed"},
                "2": {"status": "completed"},
                "3": {"status": "completed"},
                "4": {"status": "in_progress", "started_at": "2026-01-01T00:00:00"},
            },
            "history": [],
        }), encoding="utf-8")

        with patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"):
            wf = ResearchWorkflow("LEGACY")
        snap = wf.snapshot()
        # Old "4" key should be removed; new flat 0-9 keys should exist
        assert "4" not in snap["steps"] or snap["steps"]["4"]["status"] == "not_started"
        # All new steps 4-9 should be present as not_started
        for s in ("4", "5", "6", "7", "8", "9"):
            assert s in snap["steps"]


class TestResearchWorkflowExtended:
    """Additional coverage: block_step, next_step, edge cases."""

    def test_block_step_records_reason(self, tmp_path):
        wf, ws = _workflow(tmp_path)
        # Complete Step 1 and 2 so Step 3's dependencies are met
        for n in (1, 2):
            (ws / STEP_FILES[str(n)]).write_text(f"# Step {n}\n", encoding="utf-8")
        wf.sync_from_files()
        result = wf.block_step(3, reason="Missing revenue data for segment analysis")
        assert result["blocked"] is True
        assert result["step"] == "3"
        assert result["reason"] == "Missing revenue data for segment analysis"
        # Step should be blocked now
        guard = wf.can_start(3)
        assert guard["allowed"] is False
        assert "blocked" in guard["reason"]

    def test_next_step_returns_first_incomplete(self, tmp_path):
        wf, ws = _workflow(tmp_path)
        # Complete Step 1 via sync
        (ws / "step1_business_analysis.md").write_text("# Step 1\n", encoding="utf-8")
        wf.sync_from_files()

        result = wf.next_step()
        assert result["step"] == "2"
        assert result["status"] == "not_started"
        assert result["guard"]["allowed"] is True

    def test_next_step_returns_none_when_all_done(self, tmp_path):
        wf, ws = _workflow(tmp_path)
        for n in STEP_FILES:
            _write_required_artifacts(ws, n)
        wf.sync_from_files()

        result = wf.next_step()
        assert result["step"] is None
        assert result["status"] == "complete"

    def test_invalid_step_rejected(self, tmp_path):
        wf, _ = _workflow(tmp_path)
        result = wf.start_step(10)
        assert result["started"] is False
        assert "Invalid step" in result["reason"]

    def test_block_step_ignored_by_next_step(self, tmp_path):
        wf, ws = _workflow(tmp_path)
        # Complete Step 1, then block Step 2
        (ws / "step1_business_analysis.md").write_text("# Step 1\n", encoding="utf-8")
        wf.sync_from_files()
        wf.block_step(2, reason="Waiting for competitor data")

        # next_step should return Step 2 (blocked)
        result = wf.next_step()
        assert result["step"] == "2"
        assert result["status"] == "blocked"
