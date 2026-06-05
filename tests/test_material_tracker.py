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


class TestCoverageValidation:
    def test_validate_coverage_fails_missing_required_types(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_document("annual.pdf", doc_type="annual_report")
        result = tracker.validate_coverage()
        assert result["passed"] is False
        assert result["fix_required"]

    def test_validate_coverage_passes_with_required_extractions(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc = tracker.add_document("annual.pdf", doc_type="annual_report")
        for extract_type in [
            "business_overview",
            "management_guidance",
            "segment_forecast",
            "financial_fact",
            "risk_factor",
        ]:
            tracker.record_extraction(
                doc["id"],
                extract_type,
                topic=f"{extract_type} MD&A",
                value="value",
                evidence="evidence",
                tags=["mda"] if extract_type == "management_guidance" else [],
            )
        result = tracker.validate_coverage()
        assert result["passed"] is True

    def test_validate_coverage_requires_broker_assumption_when_requested(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        tracker.add_document("broker.pdf", doc_type="broker_report")
        result = tracker.validate_coverage(
            required_extraction_types=[],
            require_annual_mda=False,
            require_broker_assumptions=True,
        )
        assert result["passed"] is False
        assert "broker_assumption" in result["fix_required"][0]

    def test_pdf_read_attempt_limit_requires_fallback(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc = tracker.add_document("annual.pdf", doc_type="annual_report")

        tracker.record_read_attempt(doc["id"], "encoding_error", error="GBK decode failed", max_attempts=2)
        updated = tracker.record_read_attempt(doc["id"], "parse_error", error="garbled Chinese text", max_attempts=2)

        assert updated["fallback_required"] is True
        assert updated["read_status"] == "blocked_pdf_read"
        with pytest.raises(ValueError, match="attempt limit"):
            tracker.record_read_attempt(doc["id"], "parse_error", error="same failure", max_attempts=2)

    def test_validate_coverage_blocks_unresolved_pdf_fallback(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc = tracker.add_document("annual.pdf", doc_type="annual_report")
        tracker.record_read_attempt(doc["id"], "encoding_error", error="decode failed", max_attempts=1)

        result = tracker.validate_coverage(required_extraction_types=[])

        assert result["passed"] is False
        assert any("PDF read failed" in item for item in result["fix_required"])

    def test_web_fallback_rejects_news_or_incomplete_sources(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc = tracker.add_document("annual.pdf", doc_type="annual_report")

        with pytest.raises(ValueError, match="not news"):
            tracker.record_web_fallback(doc["id"], "https://example.com/news", "news", True)
        with pytest.raises(ValueError, match="complete"):
            tracker.record_web_fallback(doc["id"], "https://example.com/summary", "company_ir", False)

    def test_validate_coverage_rejects_unmarked_web_annual_source(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc = tracker.add_document(
            "annual.pdf",
            doc_type="annual_report",
            source_url="https://example.com/annual-report",
            source_kind="company_ir",
        )
        tracker.record_extraction(
            doc["id"],
            "management_guidance",
            topic="MD&A outlook",
            value="value",
            evidence="MD&A evidence",
            tags=["mda"],
        )

        result = tracker.validate_coverage(required_extraction_types=[])

        assert result["passed"] is False
        assert any("complete annual/interim report" in item for item in result["fix_required"])

    def test_validate_coverage_requires_explicit_mda_marker(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc = tracker.add_document("annual.pdf", doc_type="annual_report")
        for extract_type in [
            "business_overview",
            "management_guidance",
            "segment_forecast",
            "financial_fact",
            "risk_factor",
        ]:
            tracker.record_extraction(
                doc["id"],
                extract_type,
                topic=f"{extract_type} generic",
                value="value",
                evidence="evidence",
            )

        result = tracker.validate_coverage()

        assert result["passed"] is False
        assert any("MD&A" in item for item in result["fix_required"])

    def test_official_complete_fallback_with_mda_extraction_passes(self, tmp_path):
        tracker = _make_tracker(tmp_path)
        doc = tracker.add_document("annual.pdf", doc_type="annual_report")
        tracker.record_read_attempt(doc["id"], "encoding_error", error="decode failed", max_attempts=1)
        tracker.record_web_fallback(
            doc["id"],
            "https://example.com/investor-relations/annual-report.pdf",
            "company_ir",
            True,
        )
        for extract_type in [
            "business_overview",
            "management_guidance",
            "segment_forecast",
            "financial_fact",
            "risk_factor",
        ]:
            tracker.record_extraction(
                doc["id"],
                extract_type,
                topic=f"{extract_type} MD&A",
                value="value",
                evidence="MD&A evidence",
                tags=["mda"] if extract_type == "management_guidance" else [],
            )

        result = tracker.validate_coverage()

        assert result["passed"] is True
