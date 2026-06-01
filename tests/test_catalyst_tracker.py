"""Tests for src.analysis.catalyst_tracker — catalyst monitoring & kill switches.

Covers: add/resolve/mark_missed catalysts, kill switch CRUD, time decay
computation, overdue detection, and catalyst calendar.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from src.analysis.catalyst_tracker import CatalystTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tracker(tmp_path):
    """Create a CatalystTracker backed by a temp workspaces dir."""
    ws_dir = tmp_path / "workspaces" / "TEST"
    ws_dir.mkdir(parents=True, exist_ok=True)
    with patch("src.analysis.catalyst_tracker.WORKSPACES_DIR", tmp_path / "workspaces"):
        return CatalystTracker("TEST")


# ---------------------------------------------------------------------------
# Catalyst CRUD
# ---------------------------------------------------------------------------

class TestCatalystCRUD:
    def test_add_catalyst(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        cat = tracker.add_catalyst("Q2 earnings", "2026-07-15", impact="high")
        assert cat["status"] == "pending"
        assert cat["impact"] == "high"
        assert cat["id"].startswith("C")
        assert cat["event"] == "Q2 earnings"

    def test_add_catalyst_persists(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_catalyst("Event A", "2026-08-01")
        fpath = tmp_path / "workspaces" / "TEST" / "catalysts.json"
        data = json.loads(fpath.read_text())
        assert len(data["catalysts"]) == 1

    def test_resolve_catalyst(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_catalyst("Q2 earnings", "2026-07-15", impact="high")
        result = tracker.resolve_catalyst(
            "Q2 earnings", "2026-07-14", "Revenue +25%", thesis_impact="positive"
        )
        assert result["status"] == "resolved"
        assert result["outcome"] == "Revenue +25%"
        assert result["thesis_impact"] == "positive"

    def test_resolve_by_id(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        cat = tracker.add_catalyst("Event", "2026-08-01")
        result = tracker.resolve_catalyst(cat["id"], "2026-08-01", "Done")
        assert result["status"] == "resolved"

    def test_resolve_unknown_raises(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        with pytest.raises(ValueError, match="not found"):
            tracker.resolve_catalyst("nonexistent", "2026-08-01", "N/A")

    def test_mark_missed(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_catalyst("Missed event", "2026-06-01")
        result = tracker.mark_missed("Missed event", "Never happened")
        assert result["status"] == "missed"
        assert result["thesis_impact"] == "negative"

    def test_mark_missed_default_note(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_catalyst("E", "2026-06-01")
        result = tracker.mark_missed("E")
        assert "passed" in result["outcome"].lower()

    def test_multiple_catalysts(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_catalyst("C1", "2026-07-01", impact="high")
        tracker.add_catalyst("C2", "2026-08-01", impact="medium")
        tracker.add_catalyst("C3", "2026-09-01", impact="low")
        data = tracker._load()
        assert len(data["catalysts"]) == 3


# ---------------------------------------------------------------------------
# Kill switches
# ---------------------------------------------------------------------------

class TestKillSwitches:
    def test_add_kill_switch(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        ks = tracker.add_kill_switch("Gross margin < 13%", severity="critical")
        assert ks["condition"] == "Gross margin < 13%"
        assert ks["triggered"] is False
        assert ks["severity"] == "critical"

    def test_trigger_kill_switch(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_kill_switch("Margin drop")
        result = tracker.trigger_kill_switch("Margin drop", "Q2 margin fell to 11%")
        assert result["triggered"] is True
        assert result["evidence"] == "Q2 margin fell to 11%"

    def test_check_kill_switches_returns_only_triggered(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_kill_switch("Condition A")
        tracker.add_kill_switch("Condition B")
        tracker.trigger_kill_switch("Condition A", "Evidence")
        triggered = tracker.check_kill_switches()
        assert len(triggered) == 1
        assert triggered[0]["condition"] == "Condition A"

    def test_check_kill_switches_empty(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_kill_switch("Safe condition")
        assert tracker.check_kill_switches() == []

    def test_trigger_unknown_raises(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        with pytest.raises(ValueError, match="not found"):
            tracker.trigger_kill_switch("nonexistent", "no evidence")


# ---------------------------------------------------------------------------
# Time decay
# ---------------------------------------------------------------------------

class TestTimeDecay:
    def test_fresh_thesis_full_conviction(self, tmp_path):
        """Thesis created today should have modifier 1.0."""
        tracker = _make_tracker(tmp_path)
        today = date.today().isoformat()
        tracker.add_catalyst("C1", "2099-01-01")
        status = tracker.time_decay_status(thesis_created_date=today)
        assert status["conviction_modifier"] == 1.0
        assert status["phase"] == "fresh"

    def test_early_decay(self, tmp_path):
        """Day 45 → should be between 1.0 and 0.85."""
        tracker = _make_tracker(tmp_path)
        created = (date.today() - timedelta(days=45)).isoformat()
        tracker.add_catalyst("C1", "2099-01-01")
        status = tracker.time_decay_status(thesis_created_date=created)
        assert 0.85 <= status["conviction_modifier"] <= 1.0
        assert status["phase"] == "early_decay"

    def test_active_decay(self, tmp_path):
        """Day 75 → should be between 0.85 and 0.65."""
        tracker = _make_tracker(tmp_path)
        created = (date.today() - timedelta(days=75)).isoformat()
        tracker.add_catalyst("C1", "2099-01-01")
        status = tracker.time_decay_status(thesis_created_date=created)
        assert 0.65 <= status["conviction_modifier"] <= 0.85
        assert status["phase"] == "active_decay"

    def test_expired_zone(self, tmp_path):
        """Day 120 → should be <= 0.65, never below 0.40."""
        tracker = _make_tracker(tmp_path)
        created = (date.today() - timedelta(days=120)).isoformat()
        tracker.add_catalyst("C1", "2099-01-01")
        status = tracker.time_decay_status(thesis_created_date=created)
        assert status["conviction_modifier"] <= 0.65
        assert status["conviction_modifier"] >= 0.40
        assert status["phase"] == "expired_zone"

    def test_modifier_floor_at_40(self, tmp_path):
        """Very old thesis should never go below 0.40."""
        tracker = _make_tracker(tmp_path)
        created = (date.today() - timedelta(days=365)).isoformat()
        tracker.add_catalyst("C1", "2099-01-01")
        status = tracker.time_decay_status(thesis_created_date=created)
        assert status["conviction_modifier"] >= 0.40

    def test_overdue_detection(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        tracker.add_catalyst("Past event", yesterday)
        status = tracker.time_decay_status(thesis_created_date=date.today().isoformat())
        assert status["overdue_catalysts"] == 1

    def test_next_catalyst_info(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        future_date = (date.today() + timedelta(days=30)).isoformat()
        tracker.add_catalyst("Future event", future_date)
        status = tracker.time_decay_status(thesis_created_date=date.today().isoformat())
        assert status["next_catalyst"] is not None
        assert status["days_until_next_catalyst"] == 30

    def test_no_catalysts_no_crash(self, tmp_path):
        """Empty catalyst list should not crash time_decay_status."""
        tracker = _make_tracker(tmp_path)
        status = tracker.time_decay_status(thesis_created_date=date.today().isoformat())
        assert "conviction_modifier" in status


# ---------------------------------------------------------------------------
# Decay recommendation
# ---------------------------------------------------------------------------

class TestDecayRecommendation:
    def test_kill_switch_triggered_recommendation(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_kill_switch("KS")
        tracker.trigger_kill_switch("KS", "Triggered")
        status = tracker.time_decay_status(thesis_created_date=date.today().isoformat())
        assert "CRITICAL" in status["recommendation"]

    def test_fresh_recommendation(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        status = tracker.time_decay_status(thesis_created_date=date.today().isoformat())
        assert "fresh" in status["recommendation"].lower() or "Maintain conviction" in status["recommendation"]


# ---------------------------------------------------------------------------
# Catalyst calendar
# ---------------------------------------------------------------------------

class TestCatalystCalendar:
    def test_calendar_pending(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_catalyst("Event", "2099-01-01")
        cal = tracker.catalyst_calendar()
        assert "Event" in cal
        assert "⏳" in cal

    def test_calendar_resolved(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_catalyst("Done event", "2020-01-01")
        tracker.resolve_catalyst("Done event", "2020-01-01", "Result")
        cal = tracker.catalyst_calendar()
        assert "✅" in cal

    def test_calendar_kill_switch_triggered(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_kill_switch("Break condition")
        tracker.trigger_kill_switch("Break condition", "Evidence")
        cal = tracker.catalyst_calendar()
        assert "🚨" in cal
