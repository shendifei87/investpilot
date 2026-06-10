"""Tests for src.analysis.consensus_tracker — consensus and expectation gaps."""

import json
from unittest.mock import patch

import pytest

from src.analysis.consensus_tracker import ConsensusTracker, normalize_metrics


def _make_tracker(tmp_path):
    ws_dir = tmp_path / "workspaces" / "TEST"
    ws_dir.mkdir(parents=True, exist_ok=True)
    with patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"):
        return ConsensusTracker("TEST")


class TestNormalizeMetrics:
    def test_nested_metric_dict(self):
        metrics = normalize_metrics({
            "eps": {
                "2026E": {"value": 1.2, "unit": "USD/share"},
                "2027E": 1.5,
            }
        })
        assert len(metrics) == 2
        assert metrics[0]["metric"] == "eps"
        assert metrics[0]["period"] == "2026E"
        assert metrics[0]["value"] == 1.2
        assert metrics[1]["value"] == 1.5

    def test_list_metric_dict(self):
        metrics = normalize_metrics([
            {"metric": "revenue_growth", "period": "2026E", "value": "15%", "unit": "%"}
        ])
        assert metrics[0]["metric"] == "revenue_growth"
        assert metrics[0]["value"] == "15%"


class TestConsensusSnapshot:
    def test_record_snapshot_persists(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        snap = tracker.record_snapshot(
            source="Broker A",
            as_of="2026-06-01",
            metrics={"eps": {"2026E": {"value": 2.0, "unit": "CNY/share"}}},
            rating_distribution={"buy": 8, "hold": 2, "sell": 0},
            target_price=30,
        )

        assert snap["id"].startswith("CS")
        assert snap["metrics"][0]["metric"] == "eps"
        assert snap["rating_distribution"]["buy"] == 8

        fpath = tmp_path / "workspaces" / "TEST" / "consensus_snapshot.json"
        data = json.loads(fpath.read_text())
        assert data["snapshots"][0]["source"] == "Broker A"

    def test_latest_metric(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.record_snapshot(
            source="Old",
            as_of="2026-05-01",
            metrics={"eps": {"2026E": 1.0}},
        )
        tracker.record_snapshot(
            source="New",
            as_of="2026-06-01",
            metrics={"eps": {"2026E": 1.3}},
        )

        metric = tracker.latest_metric("eps", "2026E")
        assert metric["value"] == 1.3
        assert metric["source"] == "New"


class TestRevisions:
    def test_record_revision_calculates_direction(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        rev = tracker.record_revision(
            metric="eps",
            period="2026E",
            old_value=1.0,
            new_value=1.2,
            source="Consensus update",
        )
        assert rev["direction"] == "up"
        assert rev["delta"] == pytest.approx(0.2)
        assert rev["pct_change"] == pytest.approx(0.2)

    def test_record_revision_parses_percent_strings(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        rev = tracker.record_revision(
            metric="gross_margin",
            period="2026E",
            old_value="20%",
            new_value="18%",
            source="Broker update",
        )
        assert rev["direction"] == "down"
        assert rev["delta"] == pytest.approx(-0.02)


class TestExpectationGaps:
    def test_add_positive_gap(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        gap = tracker.add_expectation_gap(
            metric="eps",
            period="2026E",
            consensus_value=1.0,
            our_value=1.25,
            unit="CNY/share",
            catalyst="Q2 earnings",
        )
        assert gap["id"].startswith("EG")
        assert gap["direction"] == "positive"
        assert gap["pct_gap"] == pytest.approx(0.25)

    def test_lower_is_better_gap(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        gap = tracker.add_expectation_gap(
            metric="cost_ratio",
            period="2026E",
            consensus_value="20%",
            our_value="18%",
            lower_is_better=True,
        )
        assert gap["direction"] == "positive"
        assert gap["pct_gap"] == pytest.approx(-0.1)

    def test_resolve_gap(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        gap = tracker.add_expectation_gap("eps", "2026E", 1.0, 1.2)
        resolved = tracker.resolve_gap(gap["id"], outcome="confirmed", actual_value=1.22)
        assert resolved["status"] == "resolved"
        assert resolved["actual_value"] == 1.22

    def test_resolve_unknown_gap_raises(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        with pytest.raises(ValueError, match="not found"):
            tracker.resolve_gap("EG_missing", outcome="x")


class TestBrief:
    def test_generate_step3_brief(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.record_snapshot(
            source="Broker A",
            as_of="2026-06-01",
            metrics={"eps": {"2026E": {"value": 2.0, "unit": "CNY/share"}}},
            target_price=30,
        )
        tracker.record_revision("eps", "2026E", 1.8, 2.0, source="Broker A")
        tracker.add_expectation_gap(
            metric="eps",
            period="2026E",
            consensus_value=2.0,
            our_value=2.4,
            catalyst="Q2 earnings",
        )

        brief = tracker.generate_step3_brief()
        assert "Consensus & Expectation Gap Brief" in brief
        assert "Broker A" in brief
        assert "Open Expectation Gaps" in brief
        assert "Q2 earnings" in brief
