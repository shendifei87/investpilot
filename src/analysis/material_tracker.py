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

PDF_READ_FAILURE_STATUSES = {"failed", "error", "unreadable", "encoding_error", "parse_error"}
PDF_READ_SUCCESS_STATUSES = {"success", "partial_success"}
DISALLOWED_REPORT_SOURCE_KINDS = {
    "news",
    "article",
    "media",
    "summary",
    "press_release",
    "broker_summary",
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


def _is_mda_extraction(ext: dict) -> bool:
    """Return True only when an extraction explicitly points to MD&A/management discussion."""
    fields = [
        ext.get("topic", ""),
        ext.get("evidence", ""),
        ext.get("page", ""),
        ext.get("notes", ""),
        " ".join(str(t) for t in ext.get("tags", [])),
    ]
    haystack = " ".join(str(f).lower() for f in fields)
    markers = [
        "mda",
        "md&a",
        "management discussion",
        "management's discussion",
        "management discussion and analysis",
        "管理层讨论",
        "管理层讨论与分析",
        "经营情况讨论",
        "经营情况讨论与分析",
        "董事会报告",
    ]
    return any(marker in haystack for marker in markers)


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
        source_url: str = "",
        source_kind: str = "",
        is_complete_report: bool | None = None,
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
                "source_url": source_url or existing.get("source_url", ""),
                "source_kind": source_kind or existing.get("source_kind", ""),
                "is_complete_report": (
                    is_complete_report
                    if is_complete_report is not None
                    else existing.get("is_complete_report")
                ),
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
            "source_url": source_url,
            "source_kind": source_kind,
            "is_complete_report": is_complete_report,
            "read_attempts": [],
            "read_status": "",
            "fallback_required": False,
            "fallback_resolved": False,
            "created_at": _today(),
            "updated_at": _today(),
        }
        self._data["documents"].append(doc)
        self._save()
        return doc

    def record_read_attempt(
        self,
        document_ref: str,
        status: str,
        method: str = "pdf_text_extract",
        error: str = "",
        max_attempts: int = 2,
        notes: str = "",
    ) -> dict:
        """Record one bounded PDF-reading attempt.

        After ``max_attempts`` failed attempts, the document is marked as
        requiring a complete-report web fallback. Further failed attempts are
        rejected so the harness cannot burn tokens on the same unreadable PDF.
        """
        doc = self._find_document(document_ref)
        if not doc:
            raise ValueError(f"Document '{document_ref}' not found.")

        normalized_status = (status or "").strip().lower().replace("-", "_").replace(" ", "_")
        if normalized_status in PDF_READ_FAILURE_STATUSES and doc.get("fallback_required"):
            raise ValueError(
                f"PDF read attempt limit reached for '{doc['filename']}'. "
                "Use an official complete annual/interim report web fallback instead."
            )

        attempts = doc.setdefault("read_attempts", [])
        attempt = {
            "status": normalized_status,
            "method": method or "pdf_text_extract",
            "error": error,
            "notes": notes,
            "attempted_at": _today(),
        }
        attempts.append(attempt)

        failures = sum(1 for a in attempts if a.get("status") in PDF_READ_FAILURE_STATUSES)
        if normalized_status in PDF_READ_SUCCESS_STATUSES:
            doc["read_status"] = normalized_status
            doc["fallback_required"] = False
            doc["read_error"] = ""
        elif normalized_status in PDF_READ_FAILURE_STATUSES:
            doc["read_status"] = "blocked_pdf_read" if failures >= max_attempts else normalized_status
            doc["read_error"] = error
            if failures >= max_attempts:
                doc["fallback_required"] = True
        else:
            doc["read_status"] = normalized_status or "unknown"

        doc["updated_at"] = _today()
        self._save()
        return doc

    def record_web_fallback(
        self,
        document_ref: str,
        url: str,
        source_kind: str,
        is_complete_report: bool,
        notes: str = "",
    ) -> dict:
        """Record an official complete-report fallback for an unreadable PDF."""
        doc = self._find_document(document_ref)
        if not doc:
            raise ValueError(f"Document '{document_ref}' not found.")
        normalized_kind = (source_kind or "").strip().lower().replace("-", "_").replace(" ", "_")
        if normalized_kind in DISALLOWED_REPORT_SOURCE_KINDS:
            raise ValueError("Fallback source must be a complete annual/interim report, not news or a summary.")
        if not is_complete_report:
            raise ValueError("Fallback source must be the complete annual/interim report.")
        if not url:
            raise ValueError("Fallback URL is required.")

        doc.update({
            "source_url": url,
            "source_kind": normalized_kind or "official_complete_report",
            "is_complete_report": True,
            "fallback_required": False,
            "fallback_resolved": True,
            "read_status": "web_fallback_complete_report",
            "notes": notes or doc.get("notes", ""),
            "updated_at": _today(),
        })
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

    def validate_coverage(
        self,
        required_extraction_types: list[str] | None = None,
        require_annual_mda: bool = True,
        require_broker_assumptions: bool = False,
    ) -> dict:
        """Validate that source-material extraction is strong enough to proceed.

        This is intentionally stricter than ``coverage_summary``. It prevents a
        research step from merely indexing PDFs while leaving the actual evidence
        chain blank.
        """
        raw_required = required_extraction_types if required_extraction_types is not None else [
            "business_overview",
            "management_guidance",
            "segment_forecast",
            "financial_fact",
            "risk_factor",
        ]
        required = [
            normalize_extraction_type(t)
            for t in raw_required
        ]
        docs = self._data.get("documents", [])
        exts = self._data.get("extractions", [])
        by_type = {}
        for ext in exts:
            by_type.setdefault(ext.get("extraction_type"), []).append(ext)

        fix_required = []
        warnings = []

        missing = [t for t in required if not by_type.get(t)]
        if missing:
            fix_required.append(f"Missing required extraction types: {missing}")

        annual_docs = [d for d in docs if d.get("doc_type") in {"annual_report", "interim_report"}]
        if require_annual_mda and annual_docs:
            for doc in annual_docs:
                source_kind = str(doc.get("source_kind", "")).lower()
                if source_kind in DISALLOWED_REPORT_SOURCE_KINDS:
                    fix_required.append(
                        f"{doc.get('filename')} is indexed as an annual/interim report but source_kind={source_kind}; use the complete report, not news/summary"
                    )
                if doc.get("source_url") and doc.get("is_complete_report") is not True:
                    fix_required.append(
                        f"{doc.get('filename')} has a web source but is not marked as a complete annual/interim report"
                    )
                if doc.get("fallback_required"):
                    fix_required.append(
                        f"{doc.get('filename')} PDF read failed; record an official complete-report web fallback before continuing"
                    )
                if doc.get("fallback_resolved") and not doc.get("is_complete_report"):
                    fix_required.append(
                        f"{doc.get('filename')} fallback is not marked as a complete annual/interim report"
                    )

            mda_exts = [
                e for e in exts
                if e.get("document_type") in {"annual_report", "interim_report"}
                and _is_mda_extraction(e)
            ]
            if not mda_exts:
                fix_required.append("Annual/interim report indexed but no explicit MD&A/management-discussion extraction recorded")
        elif require_annual_mda and not annual_docs:
            fix_required.append("No annual/interim report source indexed; add a workspace PDF or official complete annual/interim report URL and read MD&A")

        broker_docs = [d for d in docs if d.get("doc_type") == "broker_report"]
        if require_broker_assumptions and broker_docs and not by_type.get("broker_assumption"):
            fix_required.append("Broker reports indexed but no broker_assumption extraction recorded")

        unextracted = [d.get("filename") for d in self.coverage_summary()["unextracted_documents"]]
        if unextracted:
            warnings.append(f"Documents indexed with no extraction: {unextracted}")

        return {
            "passed": not fix_required,
            "fix_required": fix_required,
            "warnings": warnings,
            "coverage_summary": self.coverage_summary(),
            "summary": "Material coverage sufficient" if not fix_required else f"{len(fix_required)} material coverage issue(s)",
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
