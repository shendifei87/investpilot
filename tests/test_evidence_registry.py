import json
from pathlib import Path

from src.analysis.evidence_registry import (
    build_evidence_registry,
    known_evidence_ids,
    validate_step4_evidence_contract,
)


def _write_material(ws: Path, *, fallback_required: bool = False, mda: bool = True) -> None:
    topic = "MD&A operating discussion" if mda else "Business overview"
    page = "MD&A p.12" if mda else "p.3"
    evidence = (
        "Management discussion and analysis explains volume and ASP drivers."
        if mda
        else "Company describes its business segments."
    )
    (ws / "material_extracts.json").write_text(json.dumps({
        "version": 1,
        "documents": [
            {
                "id": "DOCannual",
                "filename": "annual_report.pdf",
                "doc_type": "annual_report",
                "title": "Annual Report",
                "source_path": "annual_report.pdf",
                "read_status": "blocked_pdf_read" if fallback_required else "success",
                "fallback_required": fallback_required,
                "fallback_resolved": False,
            }
        ],
        "extractions": [
            {
                "id": "EXT001",
                "document_id": "DOCannual",
                "document_filename": "annual_report.pdf",
                "document_type": "annual_report",
                "extraction_type": "business_overview",
                "topic": topic,
                "evidence": evidence,
                "page": page,
                "confidence": "high",
                "impact": "neutral",
                "tags": ["mda"] if mda else [],
            }
        ],
    }), encoding="utf-8")


def test_build_evidence_registry_collects_material_consensus_and_artifacts(tmp_path):
    _write_material(tmp_path)
    (tmp_path / "calculated_valuation.json").write_text(
        json.dumps({"source": "calculated"}),
        encoding="utf-8",
    )
    (tmp_path / "consensus_snapshot.json").write_text(json.dumps({
        "expectation_gaps": [{"id": "GAP001", "variable": "revenue_growth"}],
        "snapshots": [{"id": "CON001", "metric": "forward_eps"}],
    }), encoding="utf-8")

    registry = build_evidence_registry(tmp_path)
    ids = {item["id"] for item in registry["evidence"]}

    assert {"DOCannual", "EXT001", "GAP001", "CON001", "calculated_valuation.json"} <= ids
    assert registry["material_coverage"]["passed"] is True
    assert (tmp_path / "evidence_registry.json").exists()


def test_known_evidence_ids_uses_registry_namespace(tmp_path):
    _write_material(tmp_path)

    ids = known_evidence_ids(tmp_path)

    assert "DOCannual" in ids
    assert "EXT001" in ids


def test_step4_evidence_contract_requires_mda(tmp_path):
    _write_material(tmp_path, mda=False)

    result = validate_step4_evidence_contract(tmp_path)

    assert result["passed"] is False
    assert any("MD&A" in item or "management-discussion" in item for item in result["fix_required"])


def test_step4_evidence_contract_rejects_unresolved_pdf_fallback(tmp_path):
    _write_material(tmp_path, fallback_required=True)

    result = validate_step4_evidence_contract(tmp_path)

    assert result["passed"] is False
    assert any("fallback" in item.lower() for item in result["fix_required"])
