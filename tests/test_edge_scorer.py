"""Tests for src.analysis.edge_scorer — investment edge classification.

Covers: 4-dimension scoring, composite grade, sustainability assessment,
concentration risk, contrarian challenges, persistence, and load_latest.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.analysis.edge_scorer import EdgeScorer, EDGE_TYPES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _default_score_args(**overrides):
    """Return a full set of valid score() args with sensible defaults."""
    args = {
        "analytical": 7,
        "analytical_reason": "Deep supply chain analysis",
        "temporal": 5,
        "temporal_reason": "Willing to hold 12 months",
        "informational": 2,
        "informational_reason": "Public info only",
        "structural": 3,
        "structural_reason": "Passive fund flows create mispricing",
    }
    args.update(overrides)
    return args


def _make_scorer(tmp_path):
    """Create an EdgeScorer backed by a temp workspace."""
    ws_dir = tmp_path / "workspaces" / "TEST"
    ws_dir.mkdir(parents=True, exist_ok=True)
    with patch("src.analysis.edge_scorer.WORKSPACES_DIR", tmp_path / "workspaces"):
        return EdgeScorer("TEST")


# ---------------------------------------------------------------------------
# Scoring basics
# ---------------------------------------------------------------------------

class TestScoring:
    def test_composite_within_range(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args())
        assert 0 <= result["composite"] <= 10

    def test_composite_weighted(self, tmp_path):
        """Composite should be a weighted average of the 4 scores."""
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args())
        raw = {
            "analytical": 7,
            "temporal": 5,
            "informational": 2,
            "structural": 3,
        }
        expected = (
            raw["analytical"] * 0.35
            + raw["temporal"] * 0.25
            + raw["informational"] * 0.20
            + raw["structural"] * 0.20
        )
        assert abs(result["composite"] - expected) < 0.01

    def test_custom_weights(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(
            **_default_score_args(),
            analytical_weight=1.0,
            temporal_weight=0.0,
            informational_weight=0.0,
            structural_weight=0.0,
        )
        assert result["composite"] == 7.0

    def test_score_validation_rejects_negative(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        with pytest.raises(ValueError, match="must be 0-10"):
            scorer.score(**_default_score_args(analytical=-1))

    def test_score_validation_rejects_over_10(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        with pytest.raises(ValueError, match="must be 0-10"):
            scorer.score(**_default_score_args(informational=11))

    def test_raw_scores_preserved(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args())
        assert result["raw_scores"]["analytical"]["score"] == 7
        assert result["raw_scores"]["analytical"]["reason"] == "Deep supply chain analysis"

    def test_all_zero_scores(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=0, temporal=0, informational=0, structural=0))
        assert result["composite"] == 0.0

    def test_perfect_scores(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=10, temporal=10, informational=10, structural=10))
        assert result["composite"] == 10.0


# ---------------------------------------------------------------------------
# Grading
# ---------------------------------------------------------------------------

class TestGrading:
    def test_grade_a(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=9, temporal=8, informational=7, structural=6))
        assert result["composite_grade"].startswith("A")

    def test_grade_b(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=6, temporal=6, informational=5, structural=5))
        assert result["composite_grade"].startswith("B")

    def test_grade_c(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=4, temporal=5, informational=3, structural=4))
        assert result["composite_grade"].startswith("C")

    def test_grade_d(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=1, temporal=2, informational=1, structural=2))
        assert result["composite_grade"].startswith("D")


# ---------------------------------------------------------------------------
# Sustainability
# ---------------------------------------------------------------------------

class TestSustainability:
    def test_low_sustainability(self, tmp_path):
        """High informational + low structural/temporal → low sustainability."""
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=8, informational=9, temporal=2, structural=1))
        assert result["sustainability"]["rating"] == "low"
        assert "1-3" in result["sustainability"]["half_life_months"]

    def test_high_sustainability(self, tmp_path):
        """Strong structural/temporal → high sustainability."""
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=3, informational=2, temporal=8, structural=7))
        assert result["sustainability"]["rating"] == "high"
        assert "6-18" in result["sustainability"]["half_life_months"]

    def test_medium_sustainability(self, tmp_path):
        """Balanced → medium sustainability."""
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=5, informational=4, temporal=5, structural=5))
        assert result["sustainability"]["rating"] == "medium"


# ---------------------------------------------------------------------------
# Concentration risk
# ---------------------------------------------------------------------------

class TestConcentration:
    def test_high_concentration(self, tmp_path):
        """One dominant score >60% of total → high concentration risk."""
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=9, temporal=1, informational=1, structural=1))
        assert result["concentration_risk"]["risk"] == "high"

    def test_low_concentration(self, tmp_path):
        """Balanced scores → low concentration risk."""
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=5, temporal=5, informational=5, structural=5))
        assert result["concentration_risk"]["risk"] == "low"

    def test_critical_concentration_all_zero(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=0, temporal=0, informational=0, structural=0))
        assert result["concentration_risk"]["risk"] == "critical"


# ---------------------------------------------------------------------------
# Contrarian challenges
# ---------------------------------------------------------------------------

class TestContrarianChallenge:
    def test_challenges_generated_for_high_scores(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=7, temporal=6, informational=6, structural=6))
        challenge = result["contrarian_challenge"]
        assert "Analytical" in challenge
        assert "Temporal" in challenge
        assert "Informational" in challenge
        assert "Structural" in challenge

    def test_no_challenge_for_low_scores(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=2, temporal=1, informational=1, structural=1))
        assert result["contrarian_challenge"] == "No strong edge to challenge."


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------

class TestRecommendation:
    def test_warning_for_d_grade(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=1, temporal=1, informational=1, structural=1))
        assert "WARNING" in result["recommendation"] or "No identifiable edge" in result["recommendation"]

    def test_kelly_reduction_for_c_grade(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        result = scorer.score(**_default_score_args(analytical=4, temporal=5, informational=3, structural=4))
        assert "reduced" in result["recommendation"].lower() or "0.5" in result["recommendation"]


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_score_persists_to_workspace(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        scorer.score(**_default_score_args())
        fpath = tmp_path / "workspaces" / "TEST" / "edge_score.json"
        assert fpath.exists()
        data = json.loads(fpath.read_text())
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["composite"] > 0

    def test_multiple_scores_append(self, tmp_path):
        scorer = _make_scorer(tmp_path)
        scorer.score(**_default_score_args(analytical=5))
        scorer.score(**_default_score_args(analytical=7))
        fpath = tmp_path / "workspaces" / "TEST" / "edge_score.json"
        data = json.loads(fpath.read_text())
        assert len(data) == 2

    def test_no_persistence_without_workspace(self, tmp_path):
        scorer = EdgeScorer()  # no workspace_dir
        result = scorer.score(**_default_score_args())
        assert result["composite"] > 0
        # Should not crash even though no file is written


# ---------------------------------------------------------------------------
# load_latest
# ---------------------------------------------------------------------------

class TestLoadLatest:
    def test_load_latest_returns_last(self, tmp_path):
        ws_dir = tmp_path / "workspaces" / "TEST"
        ws_dir.mkdir(parents=True, exist_ok=True)
        with patch("src.analysis.edge_scorer.WORKSPACES_DIR", tmp_path / "workspaces"):
            scorer = EdgeScorer("TEST")
            scorer.score(**_default_score_args(analytical=3))
            scorer.score(**_default_score_args(analytical=8))

        with patch("src.analysis.edge_scorer.WORKSPACES_DIR", tmp_path / "workspaces"):
            latest = EdgeScorer.load_latest("TEST")
            assert latest["raw_scores"]["analytical"]["score"] == 8

    def test_load_latest_returns_none_when_empty(self, tmp_path):
        ws_dir = tmp_path / "workspaces" / "EMPTY"
        ws_dir.mkdir(parents=True, exist_ok=True)
        with patch("src.analysis.edge_scorer.WORKSPACES_DIR", tmp_path / "workspaces"):
            result = EdgeScorer.load_latest("EMPTY")
            assert result is None
