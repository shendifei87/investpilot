"""Evidence Registry — unified source IDs for model assumptions.

Step 4/5/6 need a single evidence namespace instead of each validator
hand-rolling source IDs. The registry normalizes material extractions,
consensus snapshots, and generated raw-data artifacts into
``evidence_registry.json`` so assumptions can be traced back to source facts.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.analysis._base import resolve_workspace_path
from src.analysis.material_tracker import MaterialTracker
from src.storage import AtomicJSON


EVIDENCE_REGISTRY_FILENAME = "evidence_registry.json"

RAW_ARTIFACTS = {
    "calculated_valuation.json": "calculation",
    "valuation_raw_inputs.json": "raw_financial_data",
    "price_history.csv": "market_data",
    "forecast_model.json": "financial_model",
    "monte_carlo_results.json": "simulation",
}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _entry(
    evidence_id: str,
    source_type: str,
    title: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "id": evidence_id,
        "source_type": source_type,
        "title": title,
        **{k: v for k, v in extra.items() if v not in (None, "", [])},
    }


def build_evidence_registry(workspace_dir: str | Path, save: bool = True) -> dict[str, Any]:
    """Build and optionally persist the workspace evidence registry."""
    ws = resolve_workspace_path(workspace_dir)
    evidence: list[dict[str, Any]] = []

    material = _load_json(ws / "material_extracts.json")
    documents = material.get("documents") or []
    for doc in documents:
        if not isinstance(doc, dict) or not doc.get("id"):
            continue
        evidence.append(_entry(
            str(doc["id"]),
            "document",
            doc.get("title") or doc.get("filename") or str(doc["id"]),
            filename=doc.get("filename"),
            document_type=doc.get("doc_type"),
            source_path=doc.get("source_path"),
            source_url=doc.get("source_url"),
            source_kind=doc.get("source_kind"),
            is_complete_report=doc.get("is_complete_report"),
            read_status=doc.get("read_status"),
            fallback_required=doc.get("fallback_required"),
            fallback_resolved=doc.get("fallback_resolved"),
        ))

    for ext in material.get("extractions") or []:
        if not isinstance(ext, dict) or not ext.get("id"):
            continue
        evidence.append(_entry(
            str(ext["id"]),
            "material_extraction",
            ext.get("topic") or str(ext["id"]),
            document_id=ext.get("document_id"),
            document_filename=ext.get("document_filename"),
            document_type=ext.get("document_type"),
            extraction_type=ext.get("extraction_type"),
            page=ext.get("page"),
            confidence=ext.get("confidence"),
            impact=ext.get("impact"),
            tags=ext.get("tags"),
        ))

    consensus = _load_json(ws / "consensus_snapshot.json")
    for gap in consensus.get("expectation_gaps") or []:
        if isinstance(gap, dict) and gap.get("id"):
            evidence.append(_entry(
                str(gap["id"]),
                "consensus_expectation_gap",
                gap.get("variable") or gap.get("description") or str(gap["id"]),
                confidence=gap.get("confidence"),
                source=gap.get("source"),
            ))
    for snap in consensus.get("snapshots") or []:
        if isinstance(snap, dict) and snap.get("id"):
            evidence.append(_entry(
                str(snap["id"]),
                "consensus_snapshot",
                snap.get("title") or snap.get("metric") or str(snap["id"]),
                source=snap.get("source"),
            ))

    for filename, source_type in RAW_ARTIFACTS.items():
        if (ws / filename).exists():
            evidence.append(_entry(
                filename,
                source_type,
                filename,
                filename=filename,
            ))

    ids_seen: set[str] = set()
    deduped = []
    for item in evidence:
        evidence_id = str(item.get("id", "")).strip()
        if not evidence_id or evidence_id in ids_seen:
            continue
        ids_seen.add(evidence_id)
        deduped.append(item)

    material_coverage = validate_step4_evidence_contract(ws, save_registry=False)
    registry = {
        "version": 1,
        "workspace": str(ws),
        "evidence": deduped,
        "material_coverage": material_coverage,
    }
    if save:
        AtomicJSON(ws).save(EVIDENCE_REGISTRY_FILENAME, registry)
    return registry


def known_evidence_ids(workspace_dir: str | Path) -> set[str]:
    """Return all known explicit evidence IDs for a workspace."""
    registry = build_evidence_registry(workspace_dir, save=True)
    ids = {
        str(item.get("id", "")).strip()
        for item in registry.get("evidence", [])
        if item.get("id")
    }
    return {i for i in ids if i}


def validate_evidence_refs(workspace_dir: str | Path, refs: list[str]) -> dict[str, Any]:
    """Validate exact evidence IDs against the registry."""
    known = known_evidence_ids(workspace_dir)
    missing = [str(r) for r in refs if str(r) not in known]
    return {
        "passed": not missing,
        "missing": missing,
        "known_count": len(known),
        "summary": "All evidence refs resolved" if not missing else f"{len(missing)} evidence ref(s) not found",
    }


def validate_step4_evidence_contract(
    workspace_dir: str | Path,
    *,
    save_registry: bool = True,
) -> dict[str, Any]:
    """Validate evidence prerequisites for Step 4 assumption research.

    This is intentionally hard on MD&A because assumption research should not
    proceed from orphaned growth rates. If a PDF failed to parse, the material
    tracker must record an official complete-report fallback before Step 4 can
    pass.
    """
    ws = resolve_workspace_path(workspace_dir)
    material_path = ws / "material_extracts.json"
    fix_required: list[str] = []
    warnings: list[str] = []

    if not material_path.exists():
        fix_required.append(
            "material_extracts.json missing. Add/read annual or interim report material and record explicit MD&A extraction before Step 4."
        )
        coverage = {
            "passed": False,
            "fix_required": fix_required,
            "warnings": warnings,
            "summary": "Material evidence missing",
        }
    else:
        tracker = MaterialTracker(str(ws))
        coverage = tracker.validate_coverage(
            required_extraction_types=[],
            require_annual_mda=True,
            require_broker_assumptions=False,
        )

    if save_registry:
        existing = _load_json(ws / EVIDENCE_REGISTRY_FILENAME)
        existing.update({
            "version": existing.get("version", 1),
            "workspace": str(ws),
            "material_coverage": coverage,
        })
        AtomicJSON(ws).save(EVIDENCE_REGISTRY_FILENAME, existing)

    return coverage
