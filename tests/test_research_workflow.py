from unittest.mock import patch

import pytest

from src.analysis.research_workflow import ResearchWorkflow, STEP_FILES


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
        assert "Artifact not found" in result["reason"]

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
        (ws / "step4_quantitative_model.md").write_text("# Step 4\n", encoding="utf-8")
        snap = wf.sync_from_files()
        assert snap["steps"]["4"]["status"] == "not_started"


class TestResearchWorkflowExtended:
    """Additional coverage: block_step, next_step, edge cases."""

    def test_block_step_records_reason(self, tmp_path):
        wf, ws = _workflow(tmp_path)
        # Complete Step 1 and 2 so Step 3's dependencies are met
        for n in (1, 2):
            (ws / STEP_FILES[n]).write_text(f"# Step {n}\n", encoding="utf-8")
        wf.sync_from_files()
        result = wf.block_step(3, reason="Missing revenue data for segment analysis")
        assert result["blocked"] is True
        assert result["step"] == 3
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
        assert result["step"] == 2
        assert result["status"] == "not_started"
        assert result["guard"]["allowed"] is True

    def test_next_step_returns_none_when_all_done(self, tmp_path):
        wf, ws = _workflow(tmp_path)
        for n in range(1, 8):
            (ws / STEP_FILES[n]).write_text(f"# Step {n}\n", encoding="utf-8")
        wf.sync_from_files()

        result = wf.next_step()
        assert result["step"] is None
        assert result["status"] == "complete"

    def test_invalid_step_rejected(self, tmp_path):
        wf, _ = _workflow(tmp_path)
        result = wf.start_step(9)
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
        assert result["step"] == 2
        assert result["status"] == "blocked"
