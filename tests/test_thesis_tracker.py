"""Tests for src.analysis.thesis_tracker — living thesis management.

Covers: create, revise, add/confirm/invalidate hypothesis, close, snapshot,
update brief, pre-confirmation guard, and revision history.
"""

import json
from datetime import datetime, date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.analysis.thesis_tracker import ThesisTracker, ThesisStatus, HypothesisStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(tmp_path):
    """Create a ThesisTracker backed by a temp workspaces dir."""
    ws_dir = tmp_path / "workspaces" / "TEST"
    ws_dir.mkdir(parents=True, exist_ok=True)
    with patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"):
            return ThesisTracker("TEST")


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_create_first_thesis(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        rev = tracker.create("Test thesis: undervalued by market")
        assert rev["revision"] == 1
        assert rev["status"] == ThesisStatus.OPEN
        assert rev["core_thesis"] == "Test thesis: undervalued by market"
        assert rev["hold_period_months"] == 12
        assert len(rev["changelog"]) == 1
        assert rev["changelog"][0]["action"] == "thesis_created"

    def test_create_persists_to_file(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Persisted thesis")
        fpath = tmp_path / "workspaces" / "TEST" / "thesis.json"
        assert fpath.exists()
        data = json.loads(fpath.read_text())
        assert len(data["history"]) == 1

    def test_create_with_kill_switches_and_edge(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        rev = tracker.create(
            "Thesis with metadata",
            edge_type="analytical",
            edge_score={"composite": 6.5},
            kill_switches=["毛利率跌破10%", "营收增速转负"],
        )
        assert rev["edge_type"] == "analytical"
        assert rev["edge_score"]["composite"] == 6.5
        assert len(rev["kill_switches"]) == 2

    def test_create_rejects_if_open_thesis_exists(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("First thesis")
        with pytest.raises(ValueError, match="open thesis already exists"):
            tracker.create("Second thesis")

    def test_create_allows_after_close(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("First")
        tracker.close_thesis(ThesisStatus.CLOSED_WON, "Target reached")
        rev = tracker.create("Second")
        assert rev["revision"] == 1  # new thesis, revision resets


# ---------------------------------------------------------------------------
# Revise
# ---------------------------------------------------------------------------

class TestRevise:
    def test_revise_increments_revision(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Original thesis")
        rev2 = tracker.revise_thesis("Revised thesis", "New data changed view")
        assert rev2["revision"] == 2
        assert rev2["core_thesis"] == "Revised thesis"
        assert rev2["status"] == ThesisStatus.OPEN

    def test_revise_preserves_history(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("V1")
        tracker.revise_thesis("V2", "reason")
        data = tracker._load()
        assert len(data["history"]) == 2
        assert data["history"][0]["core_thesis"] == "V1"
        assert data["history"][1]["core_thesis"] == "V2"

    def test_revise_changelog_records_old_thesis(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Old")
        rev = tracker.revise_thesis("New", "Better evidence")
        last_log = rev["changelog"][-1]
        assert last_log["action"] == "thesis_revised"
        assert last_log["old_thesis"] == "Old"

    def test_revise_fails_without_thesis(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        with pytest.raises(ValueError, match="No thesis to revise"):
            tracker.revise_thesis("X", "no thesis")

    def test_revise_fails_on_closed_thesis(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("V1")
        tracker.close_thesis(ThesisStatus.CLOSED_LOST, "Thesis wrong")
        with pytest.raises(ValueError, match="Cannot revise a closed thesis"):
            tracker.revise_thesis("V2", "attempt on closed")


# ---------------------------------------------------------------------------
# Hypothesis management
# ---------------------------------------------------------------------------

class TestHypothesis:
    def test_add_hypothesis(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        hyp = tracker.add_hypothesis(
            "Revenue growth >20%",
            catalyst_date="2026-07-15",
            impact="high",
        )
        assert hyp["status"] == HypothesisStatus.PENDING
        assert hyp["impact"] == "high"
        assert hyp["id"].startswith("H")

    def test_confirm_hypothesis(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        hyp = tracker.add_hypothesis("Growth >20%", catalyst_date="2020-01-01")
        result = tracker.confirm_hypothesis("Growth >20%", actual_result="+25%")
        assert result["status"] == HypothesisStatus.CONFIRMED
        assert result["actual_result"] == "+25%"

    def test_invalidate_hypothesis(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        tracker.add_hypothesis("Growth >20%")
        result = tracker.invalidate_hypothesis("Growth >20%", actual_result="+5%")
        assert result["status"] == HypothesisStatus.INVALIDATED

    def test_pre_confirmation_guard(self, tmp_path):
        """Cannot confirm a hypothesis before its catalyst_date (future)."""
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        future = (date.today().year + 1)
        tracker.add_hypothesis("Future event", catalyst_date=f"{future}-06-30")
        with pytest.raises(ValueError, match="Cannot confirm hypothesis.*before its catalyst date"):
            tracker.confirm_hypothesis("Future event", actual_result="premature")

    def test_pre_confirmation_force_override(self, tmp_path):
        """Force override allows pre-confirmation with notes='force'."""
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        future = (date.today().year + 1)
        tracker.add_hypothesis("Override test", catalyst_date=f"{future}-06-30")
        result = tracker.confirm_hypothesis("Override test", actual_result="forced", notes="force")
        assert result["status"] == HypothesisStatus.CONFIRMED

    def test_resolve_by_id_or_description(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        hyp = tracker.add_hypothesis("Unique description", catalyst_date="2020-01-01")
        # Resolve by ID
        result = tracker.resolve_hypothesis(hyp["id"], HypothesisStatus.CONFIRMED, "ByID")
        assert result["actual_result"] == "ByID"

    def test_resolve_unknown_hypothesis_raises(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        with pytest.raises(ValueError, match="not found"):
            tracker.confirm_hypothesis("nonexistent")


# ---------------------------------------------------------------------------
# Close thesis
# ---------------------------------------------------------------------------

class TestClose:
    def test_close_won(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        result = tracker.close_thesis(ThesisStatus.CLOSED_WON, "Target hit")
        assert result["status"] == ThesisStatus.CLOSED_WON
        assert result["close_reason"] == "Target hit"

    def test_close_lost(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        result = tracker.close_thesis(ThesisStatus.CLOSED_LOST, "Thesis invalidated")
        assert result["status"] == ThesisStatus.CLOSED_LOST

    def test_close_fails_without_thesis(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        with pytest.raises(ValueError, match="No thesis to close"):
            tracker.close_thesis(ThesisStatus.CLOSED_WON, "nothing to close")


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------

class TestSnapshot:
    def test_snapshot_no_thesis(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        snap = tracker.snapshot()
        assert snap["status"] == "no_thesis"

    def test_snapshot_with_hypotheses(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        tracker.add_hypothesis("H1", catalyst_date="2020-01-01")
        tracker.confirm_hypothesis("H1", actual_result="+20%")
        tracker.add_hypothesis("H2")
        snap = tracker.snapshot()
        assert snap["hypotheses_summary"]["total"] == 2
        assert snap["hypotheses_summary"]["confirmed"] == 1
        assert snap["hypotheses_summary"]["pending"] == 1
        assert snap["hypotheses_summary"]["confirmation_rate"] == "1/1"

    def test_snapshot_confirmation_rate_na_when_no_resolved(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        tracker.add_hypothesis("Pending only")
        snap = tracker.snapshot()
        assert snap["hypotheses_summary"]["confirmation_rate"] == "N/A"


# ---------------------------------------------------------------------------
# Update brief
# ---------------------------------------------------------------------------

class TestUpdateBrief:
    def test_brief_no_thesis(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        brief = tracker.generate_update_brief()
        assert "No thesis exists" in brief

    def test_brief_contains_core_thesis(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("My core investment thesis")
        brief = tracker.generate_update_brief()
        assert "My core investment thesis" in brief
        assert "v1" in brief

    def test_brief_shows_hypothesis_status(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        tracker.add_hypothesis("Confirmed H", catalyst_date="2020-01-01")
        tracker.confirm_hypothesis("Confirmed H", actual_result="+20%")
        tracker.add_hypothesis("Pending H")
        brief = tracker.generate_update_brief()
        assert "✅" in brief  # confirmed
        assert "⏳" in brief  # pending

    def test_brief_includes_next_steps(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.create("Thesis")
        tracker.add_hypothesis("Pending hypothesis")
        brief = tracker.generate_update_brief()
        assert "Next Steps" in brief
        assert "1 hypotheses pending" in brief
