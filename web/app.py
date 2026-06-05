#!/usr/bin/env python3
"""InvestPilot Web Dashboard — localhost server with token auth and security hardening."""

from __future__ import annotations

import json
import os
import re
import sys
import secrets
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, parse_qs, unquote
from email.parser import BytesParser
from email.policy import default as default_policy

ROOT = Path(__file__).resolve().parent.parent
WORKSPACES = ROOT / "workspaces"
WEB = Path(__file__).resolve().parent

STEP_FILES = {
    0: "step0_quick_triage.md",
    1: "step1_business_analysis.md",
    2: "step2_competitive_moat.md",
    3: "step3_marginal_changes.md",
    4: "step4_quantitative_model.md",
    5: "step5_rrr_strategy.md",
    6: "step6_auditing.md",
    7: "step7_research_director_review.md",
}

STEP_NAMES = {
    0: "Quick Triage",
    1: "Business Deep Dive",
    2: "Competitive Moat",
    3: "Marginal Changes & Expectation Gap",
    4: "Quantitative Model & Simulation",
    5: "RRR & Trading Strategy",
    6: "Auditing & Quality Control",
    7: "Research Director Review",
}

CORE_STEP_NUMBERS = tuple(range(1, 8))
DISPLAY_STEP_NUMBERS = tuple(sorted(STEP_FILES))

# Security configuration
AUTH_TOKEN = os.environ.get("INVESTPILOT_TOKEN", "")
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
ALLOWED_UPLOAD_EXT = {".pdf", ".csv", ".json", ".md"}
CORS_ORIGIN = os.environ.get("INVESTPILOT_CORS_ORIGIN", "")
_WORKSPACE_NAME_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,63}$")
_MATERIAL_EXTS = {".pdf"}


def _workspace_material_files(ws_dir: Path) -> list[Path]:
    """Return user-provided material files, case-insensitive.

    Manual Finder uploads on macOS often preserve extensions like ".PDF";
    Path.glob("*.pdf") misses those and made fresh workspaces look empty.
    """
    if not ws_dir.exists():
        return []
    return [
        p for p in ws_dir.iterdir()
        if p.is_file() and p.suffix.lower() in _MATERIAL_EXTS
    ]


def get_workspace_status(ws_dir: Path) -> dict:
    material_files = _workspace_material_files(ws_dir)
    has_pdfs = bool(material_files)
    steps = {}
    completed = 0
    for n in DISPLAY_STEP_NUMBERS:
        done = (ws_dir / STEP_FILES[n]).exists()
        if n in CORE_STEP_NUMBERS and done:
            completed += 1
        steps[n] = {
            "name": STEP_NAMES[n],
            "file": STEP_FILES[n],
            "status": "completed" if done else "pending",
        }

    triage_done = steps[0]["status"] == "completed"
    status = "empty"
    if completed > 0:
        status = "in_progress"
    if completed == len(CORE_STEP_NUMBERS):
        status = "completed"
    elif triage_done and completed == 0:
        status = "triaged"
    elif has_pdfs and completed == 0:
        status = "ready"

    return {
        "has_materials": has_pdfs,
        "materials": [p.name for p in material_files],
        "steps": steps,
        "completed": completed,
        "total": len(CORE_STEP_NUMBERS),
        "triage_status": steps[0]["status"],
        "status": status,
    }


def _safe_path(base: Path, user_path: str) -> Path | None:
    """Resolve a user-supplied path and verify it stays under base directory.

    Uses Path.is_relative_to() for robust traversal prevention.
    Returns None if path escapes base.
    """
    resolved = (base / user_path).resolve()
    base_resolved = base.resolve()
    try:
        resolved.relative_to(base_resolved)
        return resolved
    except ValueError:
        return None


def _workspace_path(ticker: str) -> tuple[str, Path] | None:
    """Return a safe workspace path for a URL/body ticker."""
    normalized = unquote(str(ticker)).strip().upper()
    if not _WORKSPACE_NAME_RE.fullmatch(normalized):
        return None
    path = _safe_path(WORKSPACES, normalized)
    if path is None:
        return None
    return normalized, path


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        if CORS_ORIGIN:
            self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        else:
            self.send_header("Access-Control-Allow-Origin", f"http://localhost:{self.server.server_address[1]}")
        self.send_header("Content-Type", "application/json")

    def _check_auth(self) -> bool:
        """Check Bearer token authentication. Returns True if authenticated."""
        if not AUTH_TOKEN:
            return True  # No token configured = open access (localhost-only)
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            return secrets.compare_digest(token, AUTH_TOKEN)
        return False

    def _json(self, data, code=200):
        self.send_response(code)
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode())

    def _html(self, content, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode())

    def _unauthorized(self):
        self.send_response(401)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Unauthorized"}).encode())

    def _too_large(self):
        self.send_response(413)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"error": "Request too large"}).encode())

    def _drain_request_body(self):
        """Read and discard remaining request body before returning errors."""
        try:
            remaining = int(self.headers.get("Content-Length", 0))
        except ValueError:
            remaining = 0
        if remaining > 0:
            self.rfile.read(remaining)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        # Health check endpoint (no auth required)
        if path == "/health":
            self._json({"status": "ok", "workspaces": str(WORKSPACES)})
            return

        if not self._check_auth():
            self._unauthorized()
            return

        if path == "/" or path == "/index.html":
            html = (WEB / "index.html").read_text(encoding="utf-8")
            self._html(html)
            return

        if path == "/api/workspaces":
            results = []
            if WORKSPACES.exists():
                for d in sorted(WORKSPACES.iterdir()):
                    if d.is_dir() and not d.name.startswith("."):
                        info = get_workspace_status(d)
                        info["ticker"] = d.name
                        info["path"] = str(d)
                        info["reports"] = [f.name for f in sorted(d.glob("*_report_*.html"), reverse=True)]
                        results.append(info)
            self._json(results)
            return

        m = re.match(r"^/api/research/([^/]+)/status$", path)
        if m:
            resolved = _workspace_path(m.group(1))
            if resolved is None:
                self._json({"error": "Workspace not found"}, 404)
                return
            ticker, ws = resolved
            if not ws.exists():
                self._json({"error": "Workspace not found"}, 404)
                return
            info = get_workspace_status(ws)
            info["ticker"] = ticker
            info["images"] = [f.name for f in ws.glob("*.png")]
            info["reports"] = [f.name for f in sorted(ws.glob("*_report_*.html"), reverse=True)]
            self._json(info)
            return

        m = re.match(r"^/api/research/([^/]+)/step/(\d+)$", path)
        if m:
            resolved = _workspace_path(m.group(1))
            if resolved is None:
                self._json({"error": "Step not found"}, 404)
                return
            ticker, ws = resolved
            step = int(m.group(2))
            step_filename = STEP_FILES.get(step)
            if not step_filename:
                self._json({"error": "Step not found"}, 404)
                return
            step_file = ws / step_filename
            if not step_file.exists():
                self._json({"error": "Step not found"}, 404)
                return
            content = step_file.read_text(encoding="utf-8")
            self._json({"ticker": ticker, "step": step, "content": content})
            return

        m = re.match(r"^/api/research/([^/]+)/image/(.+)$", path)
        if m:
            resolved = _workspace_path(m.group(1))
            if resolved is None:
                self._json({"error": "Not found"}, 404)
                return
            ticker, ws = resolved
            img = unquote(m.group(2))
            img_path = _safe_path(ws, img)
            if img_path is None or not img_path.exists() or img_path.suffix.lower() != ".png":
                self._json({"error": "Not found"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(img_path.read_bytes())
            return

        m = re.match(r"^/api/research/([^/]+)/report/(.+)$", path)
        if m:
            resolved = _workspace_path(m.group(1))
            if resolved is None:
                self._json({"error": "Not found"}, 404)
                return
            ticker, ws = resolved
            filename = unquote(m.group(2))
            file_path = _safe_path(ws, filename)
            if file_path is None or not file_path.exists() or file_path.suffix.lower() != ".html":
                self._json({"error": "Not found"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(file_path.read_bytes())
            return

        self._json({"error": "Not found"}, 404)

    def do_POST(self):
        if not self._check_auth():
            self._unauthorized()
            return

        # Enforce request size limit
        try:
            content_length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self._json({"error": "Invalid Content-Length"}, 400)
            return
        if content_length > MAX_UPLOAD_BYTES:
            self._too_large()
            return

        parsed = urlparse(self.path)
        if parsed.path == "/api/research":
            try:
                body = json.loads(self.rfile.read(content_length)) if content_length else {}
            except json.JSONDecodeError:
                self._json({"error": "Invalid JSON"}, 400)
                return
            ticker = body.get("ticker", "").strip().upper()
            notes = body.get("notes", "").strip()

            if not ticker:
                self._json({"error": "Ticker is required"}, 400)
                return

            resolved = _workspace_path(ticker)
            if resolved is None:
                self._json({"error": "Invalid ticker"}, 400)
                return
            ticker, ws = resolved
            ws.mkdir(parents=True, exist_ok=True)

            if notes:
                (ws / "user_notes.md").write_text(f"# User Notes\n\n{notes}\n", encoding="utf-8")

            self._json({
                "ticker": ticker,
                "path": str(ws),
                "message": f"Workspace created at {ws}. Please add annual reports and research PDFs.",
            })
            return

        m = re.match(r"^/api/research/([^/]+)/upload$", parsed.path)
        if m:
            self._handle_upload(m.group(1))
            return

        self._json({"error": "Not found"}, 404)

    def _parse_multipart(self):
        content_type = self.headers.get("Content-Type", "")
        if "boundary=" not in content_type:
            return []
        boundary = content_type.split("boundary=")[1].strip()
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)

        boundary_bytes = boundary.encode()
        parts = raw.split(b"--" + boundary_bytes)
        files = []
        for part in parts[1:]:
            if part.strip() in (b"", b"--\r\n", b"--"):
                continue
            if b"\r\n\r\n" not in part:
                continue
            header_section, body = part.split(b"\r\n\r\n", 1)
            if body.endswith(b"\r\n"):
                body = body[:-2]
            if body.endswith(b"--"):
                body = body[:-2]

            header_text = header_section.decode("utf-8", errors="replace")
            filename = None
            for line in header_text.split("\r\n"):
                if "filename=" in line:
                    for seg in line.split(";"):
                        seg = seg.strip()
                        if seg.startswith("filename="):
                            filename = seg.split("=", 1)[1].strip('"')
            if filename:
                files.append({"filename": filename, "data": body})
        return files

    def _handle_upload(self, ticker):
        resolved = _workspace_path(ticker)
        if resolved is None:
            self._drain_request_body()
            self._json({"error": "Invalid ticker"}, 400)
            return
        ticker, ws = resolved
        if not ws.exists():
            self._drain_request_body()
            self._json({"error": "Workspace not found"}, 404)
            return

        files = self._parse_multipart()
        uploaded = []
        skipped = []

        for f in files:
            name = Path(f["filename"]).name
            ext = Path(name).suffix.lower()
            if ext not in ALLOWED_UPLOAD_EXT:
                skipped.append({"name": name, "reason": f"Extension {ext} not allowed"})
                continue
            dest = ws / name
            if dest.exists():
                skipped.append({"name": name, "reason": "File already exists"})
                continue
            dest.write_bytes(f["data"])
            uploaded.append(name)

        self._json({"uploaded": uploaded, "skipped": skipped})

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = HTTPServer(("localhost", port), Handler)

    auth_status = "enabled (INVESTPILOT_TOKEN set)" if AUTH_TOKEN else "disabled (set INVESTPILOT_TOKEN env var to enable)"
    print(f"InvestPilot Dashboard: http://localhost:{port}")
    print(f"Authentication: {auth_status}")
    print(f"Max upload size: {MAX_UPLOAD_BYTES // (1024*1024)} MB")
    print(f"Workspaces: {WORKSPACES}")
    print(f"Health check: http://localhost:{port}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


if __name__ == "__main__":
    main()
