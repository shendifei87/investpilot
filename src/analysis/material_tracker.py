"""Material Tracker — structured extraction from annual reports and broker PDFs.

The goal is to turn source-material reading into reusable research assets.
Each PDF/report can be indexed as a document, and key findings can be recorded
as typed extractions (management guidance, segment forecasts, valuation methods,
risk factors, thesis-conflicting evidence, etc.).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

from src.analysis._base import WorkspaceStateBase


DOCUMENT_TYPES = {
    "annual_report",
    "interim_report",
    "quarterly_report",
    "broker_report",
    "company_announcement",
    "transcript",
    "presentation",
    "other",
}

EXTRACTION_TYPES = {
    "business_overview",
    "management_guidance",
    "segment_forecast",
    "broker_assumption",
    "valuation_method",
    "risk_factor",
    "thesis_conflict",
    "moat_evidence",
    "financial_fact",
    "catalyst",
    "other",
}

_BRIEF_ORDER = [
    "management_guidance",
    "segment_forecast",
    "broker_assumption",
    "valuation_method",
    "risk_factor",
    "thesis_conflict",
    "moat_evidence",
    "financial_fact",
    "catalyst",
]


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _id(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:6]}"


def _normalize_choice(value: str, allowed: set[str], fallback: str) -> str:
    value = (value or fallback).strip().lower().replace("-", "_").replace(" ", "_")
    return value if value in allowed else fallback


def normalize_document_type(doc_type: str) -> str:
    return _normalize_choice(doc_type, DOCUMENT_TYPES, "other")


def normalize_extraction_type(extraction_type: str) -> str:
    return _normalize_choice(extraction_type, EXTRACTION_TYPES, "other")


def _short(text: Any, max_len: int = 90) -> str:
    s = "" if text is None else str(text)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


class MaterialTracker(WorkspaceStateBase):
    """Manages structured source material extraction in a workspace."""

    _state_file = "material_extracts.json"
    _default_state = {
        "version": 1,
        "documents": [],
        "extractions": [],
    }

    def _find_document(self, document_ref: str) -> dict | None:
        ref = str(document_ref)
        for doc in self._data.get("documents", []):
            if doc["id"] == ref or doc.get("filename") == ref or doc.get("source_path") == ref:
                return doc
        return None

    def add_document(
        self,
        filename: str,
        doc_type: str = "other",
        title: str = "",
        issuer: str = "",
        publish_date: str = "",
        period: str = "",
        source_path: str = "",
        pages: int | None = None,
        language: str = "",
        notes: str = "",
    ) -> dict:
        """Add or update a source document record."""
        filename = Path(filename).name
        source_path = source_path or filename

        existing = self._find_document(source_path) or self._find_document(filename)
        if existing:
            existing.update({
                "filename": filename,
                "doc_type": normalize_document_type(doc_type),
                "title": title or existing.get("title", ""),
                "issuer": issuer or existing.get("issuer", ""),
                "publish_date": publish_date or existing.get("publish_date", ""),
                "period": period or existing.get("period", ""),
                "source_path": source_path,
                "pages": pages if pages is not None else existing.get("pages"),
                "language": language or existing.get("language", ""),
                "notes": notes or existing.get("notes", ""),
                "updated_at": _today(),
            })
            self._save()
            return existing

        doc = {
            "id": _id("DOC"),
            "filename": filename,
            "doc_type": normalize_document_type(doc_type),
            "title": title,
            "issuer": issuer,
            "publish_date": publish_date,
            "period": period,
            "source_path": source_path,
            "pages": pages,
            "language": language,
            "notes": notes,
            "created_at": _today(),
            "updated_at": _today(),
        }
        self._data["documents"].append(doc)
        self._save()
        return doc

    def index_workspace_files(
        self,
        extensions: tuple[str, ...] = (".pdf", ".md", ".csv", ".json"),
    ) -> dict:
        """Index source-like files already present in the workspace.

        Existing document records are updated in place; generated state files
        and report outputs are skipped.
        """
        skip_names = {
            "thesis.json",
            "catalysts.json",
            "edge_score.json",
            "consensus_snapshot.json",
            "material_extracts.json",
            "_knowledge_graph.json",
            "_reviewed_assumptions.json",
            "calibration_record.json",
        }
        docs = []
        skipped = []
        for path in sorted(self.workspace.iterdir()):
            if not path.is_file():
                continue
            if path.name in skip_names or path.name.startswith("."):
                skipped.append(path.name)
                continue
            if path.suffix.lower() not in extensions:
                skipped.append(path.name)
                continue
            if path.name.endswith(".bak") or "_report_" in path.name:
                skipped.append(path.name)
                continue

            doc_type = "broker_report" if path.suffix.lower() == ".pdf" else "other"
            lower_name = path.name.lower()
            if any(token in lower_name for token in ["annual", "年报", "10-k"]):
                doc_type = "annual_report"
            elif any(token in lower_name for token in ["interim", "中报", "半年度"]):
                doc_type = "interim_report"
            elif any(token in lower_name for token in ["quarter", "季度", "10-q"]):
                doc_type = "quarterly_report"

            docs.append(self.add_document(
                filename=path.name,
                doc_type=doc_type,
                title=path.stem,
                source_path=path.name,
            ))

        return {
            "indexed": docs,
            "skipped": skipped,
            "n_indexed": len(docs),
            "n_skipped": len(skipped),
        }

    def record_extraction(
        self,
        document_ref: str,
        extraction_type: str,
        topic: str,
        value: Any,
        evidence: str,
        page: str | int | None = None,
        confidence: str = "medium",
        impact: str = "neutral",
        tags: list[str] | None = None,
        source_quote: str = "",
        notes: str = "",
    ) -> dict:
        """Record a typed extraction from a source document."""
        doc = self._find_document(document_ref)
        if not doc:
            raise ValueError(f"Document '{document_ref}' not found.")

        extraction = {
            "id": _id("EXT"),
            "document_id": doc["id"],
            "document_filename": doc["filename"],
            "document_type": doc["doc_type"],
            "extraction_type": normalize_extraction_type(extraction_type),
            "topic": topic,
            "value": value,
            "evidence": evidence,
            "source_quote": source_quote,
            "page": str(page) if page is not None else "",
            "confidence": confidence,
            "impact": impact,
            "tags": tags or [],
            "notes": notes,
            "created_at": _today(),
        }
        self._data["extractions"].append(extraction)
        self._save()
        return extraction

    def extractions(
        self,
        extraction_type: str = "",
        document_ref: str = "",
        tag: str = "",
    ) -> list[dict]:
        """Filter extractions by type, document, or tag."""
        out = list(self._data.get("extractions", []))
        if extraction_type:
            wanted = normalize_extraction_type(extraction_type)
            out = [e for e in out if e.get("extraction_type") == wanted]
        if document_ref:
            doc = self._find_document(document_ref)
            if not doc:
                return []
            out = [e for e in out if e.get("document_id") == doc["id"]]
        if tag:
            out = [e for e in out if tag in e.get("tags", [])]
        return out

    def coverage_summary(self) -> dict:
        docs = self._data.get("documents", [])
        exts = self._data.get("extractions", [])
        by_doc_type = {}
        by_extraction_type = {}
        for doc in docs:
            by_doc_type[doc["doc_type"]] = by_doc_type.get(doc["doc_type"], 0) + 1
        for ext in exts:
            kind = ext["extraction_type"]
            by_extraction_type[kind] = by_extraction_type.get(kind, 0) + 1

        docs_with_extracts = {e["document_id"] for e in exts}
        unextracted = [d for d in docs if d["id"] not in docs_with_extracts]

        return {
            "n_documents": len(docs),
            "n_extractions": len(exts),
            "by_document_type": by_doc_type,
            "by_extraction_type": by_extraction_type,
            "unextracted_documents": unextracted,
        }

    def snapshot(self) -> dict:
        return self._data

    def generate_research_brief(self, focus: str = "all") -> str:
        """Generate a markdown brief for Step 1-4 analysis."""
        focus = focus.lower()
        summary = self.coverage_summary()
        lines = [
            "## Source Material Extraction Brief",
            "",
            f"**Documents indexed**: {summary['n_documents']} | **Structured extractions**: {summary['n_extractions']}",
            "",
        ]

        docs = self._data.get("documents", [])
        if docs:
            lines.extend([
                "### Documents",
                "",
                "| ID | Type | Title / Filename | Issuer | Date | Period |",
                "|:--|:--|:--|:--|:--|:--|",
            ])
            for doc in docs:
                title = doc.get("title") or doc.get("filename")
                lines.append(
                    f"| {doc['id']} | {doc['doc_type']} | {_short(title)} | "
                    f"{doc.get('issuer', '')} | {doc.get('publish_date', '')} | {doc.get('period', '')} |"
                )
        else:
            lines.append("No source documents indexed yet.")

        allowed = _BRIEF_ORDER if focus == "all" else [normalize_extraction_type(focus)]
        for kind in allowed:
            items = self.extractions(kind)
            if not items:
                continue
            title = kind.replace("_", " ").title()
            lines.extend(["", f"### {title}", ""])
            lines.append("| Topic | Value | Evidence | Source | Page | Confidence | Impact |")
            lines.append("|:--|:--|:--|:--|:--|:--|:--|")
            for ext in items:
                lines.append(
                    f"| {_short(ext['topic'])} | {_short(ext['value'])} | {_short(ext['evidence'])} | "
                    f"{ext['document_filename']} | {ext.get('page', '')} | "
                    f"{ext.get('confidence', '')} | {ext.get('impact', '')} |"
                )

        if summary["unextracted_documents"]:
            lines.extend(["", "### Extraction Gaps", ""])
            for doc in summary["unextracted_documents"]:
                lines.append(f"- {doc['filename']} has no structured extraction yet.")

        lines.extend([
            "",
            "### Usage Notes",
            "",
            "- Step 1 should prioritize annual/interim report MD&A and management guidance extractions.",
            "- Step 2 should use moat evidence, risk factors, and broker assumptions.",
            "- Step 3 should convert sell-side assumptions into `consensus_snapshot.json` when they represent market consensus.",
            "- Step 4 should use segment forecasts and valuation methods only as evidence anchors, not as copied target-price math.",
        ])

        return "\n".join(lines)
