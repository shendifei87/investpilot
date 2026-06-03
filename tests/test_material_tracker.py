"""Tests for src.analysis.material_tracker — source material extraction."""

import json
from unittest.mock import patch

import pytest

from src.analysis.material_tracker import (
    MaterialTracker,
    normalize_document_type,
    normalize_extraction_type,
)


def _make_tracker(tmp_path):
    ws_dir = tmp_path / "workspaces" / "TEST"
    ws_dir.mkdir(parents=True, exist_ok=True)
    with patch("src.analysis._base.WORKSPACES_DIR", tmp_path / "workspaces"):
        return MaterialTracker("TEST")


class TestNormalization:
    def test_document_type_normalization(self):
        assert normalize_document_type("annual-report") == "annual_report"
        assert normalize_document_type("unknown") == "other"

    def test_extraction_type_normalization(self):
        assert normalize_extraction_type("management guidance") == "management_guidance"
        assert normalize_extraction_type("nope") == "other"


class TestDocuments:
    def test_add_document_persists(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc = tracker.add_document(
            "annual_report.pdf",
            doc_type="annual_report",
            title="2025 Annual Report",
            issuer="TEST Corp",
            publish_date="2026-04-30",
            period="2025A",
            pages=120,
        )

        assert doc["id"].startswith("DOC")
        assert doc["doc_type"] == "annual_report"
        fpath = tmp_path / "workspaces" / "TEST" / "material_extracts.json"
        data = json.loads(fpath.read_text())
        assert data["documents"][0]["title"] == "2025 Annual Report"

    def test_add_document_updates_existing_by_filename(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        first = tracker.add_document("report.pdf", doc_type="broker_report")
        second = tracker.add_document("report.pdf", doc_type="annual_report", title="Updated")
        assert first["id"] == second["id"]
        assert second["doc_type"] == "annual_report"
        assert len(tracker.snapshot()["documents"]) == 1

    def test_index_workspace_files(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        ws = tmp_path / "workspaces" / "TEST"
        (ws / "2025_annual_report.pdf").write_bytes(b"%PDF fake")
        (ws / "broker_note.pdf").write_bytes(b"%PDF fake")
        (ws / "thesis.json").write_text("{}")
        (ws / "TEST_report_20260603.html").write_text("<html></html>")

        result = tracker.index_workspace_files()
        assert result["n_indexed"] == 2
        docs = tracker.snapshot()["documents"]
        assert {d["doc_type"] for d in docs} == {"annual_report", "broker_report"}


class TestExtractions:
    def test_record_extraction(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc = tracker.add_document("annual_report.pdf", doc_type="annual_report")
        ext = tracker.record_extraction(
            document_ref=doc["id"],
            extraction_type="management_guidance",
            topic="Margin outlook",
            value="Management expects stable gross margin",
            evidence="MD&A states pricing discipline offsets cost pressure",
            page="MD&A p.18",
            confidence="high",
            impact="positive",
            tags=["step1", "mda"],
        )

        assert ext["id"].startswith("EXT")
        assert ext["document_id"] == doc["id"]
        assert ext["extraction_type"] == "management_guidance"
        assert "step1" in ext["tags"]

    def test_record_extraction_unknown_document_raises(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        with pytest.raises(ValueError, match="Document"):
            tracker.record_extraction("missing.pdf", "risk_factor", "Risk", "x", "evidence")

    def test_filter_extractions_by_type_and_tag(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc = tracker.add_document("broker.pdf", doc_type="broker_report")
        tracker.record_extraction(doc["id"], "segment_forecast", "Cloud growth", "+20%", "Model table", tags=["step4"])
        tracker.record_extraction(doc["id"], "risk_factor", "Competition", "High", "Risk section", tags=["step2"])

        assert len(tracker.extractions("segment_forecast")) == 1
        assert len(tracker.extractions(tag="step2")) == 1
        assert tracker.extractions("segment_forecast")[0]["topic"] == "Cloud growth"


class TestBrief:
    def test_coverage_summary(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc1 = tracker.add_document("annual.pdf", doc_type="annual_report")
        tracker.add_document("broker.pdf", doc_type="broker_report")
        tracker.record_extraction(doc1["id"], "financial_fact", "Revenue", "100", "Income statement")

        summary = tracker.coverage_summary()
        assert summary["n_documents"] == 2
        assert summary["n_extractions"] == 1
        assert len(summary["unextracted_documents"]) == 1

    def test_generate_research_brief(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc = tracker.add_document("annual.pdf", doc_type="annual_report", title="Annual")
        tracker.record_extraction(
            doc["id"],
            "management_guidance",
            "Revenue outlook",
            "Double-digit growth",
            "MD&A guidance",
            page=12,
            confidence="high",
        )

        brief = tracker.generate_research_brief()
        assert "Source Material Extraction Brief" in brief
        assert "Management Guidance" in brief
        assert "Revenue outlook" in brief
