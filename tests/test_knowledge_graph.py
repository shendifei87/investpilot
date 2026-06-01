"""Tests for src.analysis.knowledge_graph — v2 graph-based knowledge accumulation.

Validates migration, normalization, deduplication, fuzzy matching,
and API contract preservation.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.analysis.knowledge_graph import (
    KnowledgeGraph,
    _normalize_moat,
    _migrate_v1_to_v2,
)


# ── Unit tests ──────────────────────────────────────────────────

class TestNormalizeMoat:
    def test_lowercase(self):
        assert _normalize_moat("narrow") == "narrow"

    def test_mixed_case(self):
        assert _normalize_moat("Narrow") == "narrow"

    def test_uppercase(self):
        assert _normalize_moat("WIDE") == "wide"

    def test_underscore_variant(self):
        assert _normalize_moat("Narrow_Widening") == "narrow_widening"

    def test_hyphen_variant(self):
        assert _normalize_moat("narrow-widening") == "narrow_widening"

    def test_space_variant(self):
        assert _normalize_moat("narrow widening") == "narrow_widening"

    def test_empty(self):
        assert _normalize_moat("") == ""

    def test_unknown_passes_through(self):
        assert _normalize_moat("custom_rating") == "custom_rating"


class TestMigration:
    def _make_v1(self):
        return {
            "version": 1,
            "companies": {
                "600584": [
                    {
                        "ticker": "600584",
                        "workspace": "600584.SH",
                        "date": "2026-05-29",
                        "industry": "半导体封测",
                        "themes": ["Chiplet", "先进封装"],
                        "thesis": "先进封装产能释放",
                        "rrr": 2.3,
                        "moat_rating": "Narrow",
                        "edge_composite": 5.0,
                        "eqc_grade": "B",
                        "key_metrics": {},
                        "outcome": "",
                    },
                ],
            },
            "industries": {"半导体封测": [{"ticker": "600584", "date": "2026-05-29"}]},
            "themes": {
                "Chiplet": [{"ticker": "600584", "date": "2026-05-29"}],
                "先进封装": [{"ticker": "600584", "date": "2026-05-29"}],
            },
            "patterns": [],
            "lessons": [],
        }

    def test_v1_to_v2_structure(self):
        v2 = _migrate_v1_to_v2(self._make_v1())
        assert v2["version"] == 2
        assert "600584" in v2["companies"]
        assert "edges" in v2

    def test_v1_to_v2_moat_normalized(self):
        v2 = _migrate_v1_to_v2(self._make_v1())
        assert v2["companies"]["600584"]["current"]["moat_rating"] == "narrow"

    def test_v1_to_v2_edges_created(self):
        v2 = _migrate_v1_to_v2(self._make_v1())
        edge_types = {(e["source"], e["target"], e["type"]) for e in v2["edges"]}
        assert ("600584", "半导体封测", "company_industry") in edge_types
        assert ("600584", "Chiplet", "company_theme") in edge_types
        assert ("600584", "先进封装", "company_theme") in edge_types

    def test_v1_to_v2_no_old_keys(self):
        v2 = _migrate_v1_to_v2(self._make_v1())
        assert "industries" not in v2
        assert "themes" not in v2

    def test_v2_passthrough(self):
        v2 = {"version": 2, "companies": {}, "edges": []}
        assert _migrate_v1_to_v2(v2) is v2

    def test_v1_multiple_records_become_history(self):
        v1 = self._make_v1()
        v1["companies"]["600584"].insert(0, {
            "ticker": "600584", "workspace": "600584.SH",
            "date": "2026-05-28", "industry": "半导体封测",
            "themes": ["Chiplet"], "thesis": "old thesis",
            "rrr": 1.5, "moat_rating": "narrow",
        })
        v2 = _migrate_v1_to_v2(v1)
        company = v2["companies"]["600584"]
        assert len(company["history"]) == 1
        assert company["history"][0]["thesis"] == "old thesis"
        assert company["current"]["thesis"] == "先进封装产能释放"


# ── Integration tests ───────────────────────────────────────────

class TestKnowledgeGraphIntegration:
    """Integration tests using temp directory for persistence."""

    @pytest.fixture
    def kg(self, tmp_path):
        """Create a KnowledgeGraph with a temp workspace dir."""
        with patch("src.analysis.knowledge_graph.WORKSPACES_DIR", tmp_path):
            tmp_path.mkdir(parents=True, exist_ok=True)
            return KnowledgeGraph()

    def test_record_and_find(self, kg):
        kg.record_research("WS1", "T1", "半导体封测", ["Chiplet"], "thesis", rrr=2.0, moat_rating="Narrow")
        results = kg.find_similar(industry="半导体封测")
        assert len(results) == 1
        assert results[0]["ticker"] == "T1"
        assert results[0]["similarity"] == 1.0

    def test_dedup_on_reresearch(self, kg):
        kg.record_research("WS1", "T1", "半导体封测", ["Chiplet"], "thesis1", rrr=2.0)
        kg.record_research("WS1", "T1", "半导体封测", ["Chiplet", "AI芯片"], "thesis2", rrr=3.0)

        company = kg._data["companies"]["T1"]
        assert company["current"]["thesis"] == "thesis2"
        assert len(company["history"]) == 1
        assert company["history"][0]["thesis"] == "thesis1"

        # No duplicate industry edges
        industry_edges = [e for e in kg._data["edges"] if e["type"] == "company_industry"]
        assert len(industry_edges) == 1

    def test_moat_normalized(self, kg):
        kg.record_research("WS1", "T1", "ind", [], "t", moat_rating="Narrow_Widening")
        assert kg._data["companies"]["T1"]["current"]["moat_rating"] == "narrow_widening"

    def test_find_similar_by_theme(self, kg):
        kg.record_research("WS1", "T1", "ind1", ["AI芯片", "Chiplet"], "t1", rrr=2.0)
        kg.record_research("WS2", "T2", "ind2", ["AI芯片", "GPU"], "t2", rrr=1.5)
        results = kg.find_similar(themes=["AI芯片"])
        tickers = {r["ticker"] for r in results}
        assert "T1" in tickers
        assert "T2" in tickers

    def test_find_similar_by_moat(self, kg):
        kg.record_research("WS1", "T1", "ind1", [], "t1", moat_rating="wide")
        kg.record_research("WS2", "T2", "ind2", [], "t2", moat_rating="narrow")
        results = kg.find_similar(moat_rating="wide")
        tickers = {r["ticker"] for r in results}
        assert "T1" in tickers
        assert "T2" not in tickers

    def test_record_outcome(self, kg):
        kg.record_research("WS1", "T1", "ind", [], "thesis")
        result = kg.record_outcome("T1", "won", return_pct=25.0, hold_days=60)
        assert result["outcome"] == "won"
        assert result["return_pct"] == 25.0
        assert result["hold_days"] == 60

    def test_record_outcome_unknown_ticker_raises(self, kg):
        with pytest.raises(ValueError, match="No research record"):
            kg.record_outcome("UNKNOWN", "lost")

    def test_industry_insights(self, kg):
        kg.record_research("WS1", "T1", "半导体封测", ["Chiplet"], "t1", rrr=2.0)
        kg.record_research("WS2", "T2", "半导体封测", ["先进封装"], "t2", rrr=1.5)
        insights = kg.get_industry_insights("半导体封测")
        assert insights["n_research"] == 2
        assert set(insights["tickers_analyzed"]) == {"T1", "T2"}
        assert insights["avg_rrr"] == 1.75
        assert "Chiplet" in insights["related_themes"]
        assert "先进封装" in insights["related_themes"]

    def test_theme_insights(self, kg):
        kg.record_research("WS1", "T1", "半导体封测", ["Chiplet"], "t1")
        insights = kg.get_theme_insights("Chiplet")
        assert insights["n_research"] == 1
        assert "T1" in insights["tickers"]
        assert "半导体封测" in insights["industries"]

    def test_theme_insights_no_match(self, kg):
        insights = kg.get_theme_insights("不存在")
        assert insights["n_research"] == 0

    def test_add_lesson_and_query(self, kg):
        kg.add_lesson("高增速板块占比提升时需关注持续性", "半导体行业", ["T1"])
        results = kg.query_patterns("高增速")
        assert len(results) == 1
        assert results[0]["type"] == "lesson"

    def test_add_pattern(self, kg):
        kg.add_pattern("产能释放后毛利率拐点", ["产能利用率>80%"], ["毛利率回升"], "untested")
        results = kg.query_patterns("产能")
        assert len(results) == 1
        assert results[0]["type"] == "pattern"

    def test_cross_workspace_stats(self, kg):
        kg.record_research("WS1", "T1", "ind1", ["theme1"], "t1", rrr=2.0)
        kg.record_research("WS2", "T2", "ind2", ["theme2"], "t2", rrr=1.5)
        stats = kg.cross_workspace_stats()
        assert stats["total_research"] == 2
        assert stats["avg_rrr"] == 1.75

    def test_generate_research_brief(self, kg):
        kg.record_research("WS1", "T1", "半导体封测", ["Chiplet"], "thesis text", rrr=2.0)
        brief = kg.generate_research_brief("T2", "半导体封测", ["Chiplet"])
        assert "半导体封测" in brief
        assert "Chiplet" in brief
        assert "T1" in brief

    def test_edges_survive_multiple_records(self, kg):
        kg.record_research("WS1", "T1", "ind1", ["t1", "t2"], "thesis1")
        kg.record_research("WS1", "T1", "ind2", ["t3"], "thesis2")
        edges = kg._data["edges"]
        industry_edges = [e for e in edges if e["source"] == "T1" and e["type"] == "company_industry"]
        theme_edges = [e for e in edges if e["source"] == "T1" and e["type"] == "company_theme"]
        # Only 1 industry edge (latest), and only 1 theme edge (latest)
        assert len(industry_edges) == 1
        assert industry_edges[0]["target"] == "ind2"
        assert len(theme_edges) == 1
        assert theme_edges[0]["target"] == "t3"

    def test_persistence_roundtrip(self, tmp_path):
        """Data survives save/load cycle."""
        with patch("src.analysis.knowledge_graph.WORKSPACES_DIR", tmp_path):
            tmp_path.mkdir(parents=True, exist_ok=True)
            kg1 = KnowledgeGraph()
            kg1.record_research("WS1", "T1", "ind1", ["t1"], "thesis", rrr=2.0, moat_rating="Narrow")

        # New instance should see the data
        with patch("src.analysis.knowledge_graph.WORKSPACES_DIR", tmp_path):
            kg2 = KnowledgeGraph()
            results = kg2.find_similar(industry="ind1")
            assert len(results) == 1
            assert results[0]["ticker"] == "T1"
