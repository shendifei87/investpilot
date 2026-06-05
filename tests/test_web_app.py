"""Tests for the InvestPilot Web Dashboard (web/app.py).

Covers: health check, API endpoints, authentication, path traversal
prevention, file upload validation, and workspace status.
"""

import json
import sys
import threading
import time
from pathlib import Path
from http.client import HTTPConnection
from urllib.parse import urlencode

import pytest

# Ensure project root on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from web.app import Handler, get_workspace_status, _safe_path, _workspace_path, STEP_FILES


# ─── Unit tests for helper functions ─────────────────────────────────


class TestGetWorkspaceStatus:
    """Tests for get_workspace_status()."""

    def test_empty_workspace(self, tmp_workspace):
        status = get_workspace_status(tmp_workspace)
        assert status["status"] == "empty"
        assert status["completed"] == 0
        assert status["total"] == 7
        assert status["triage_status"] == "pending"
        assert status["steps"][0]["file"] == "step0_quick_triage.md"
        assert not status["has_materials"]

    def test_workspace_with_pdfs(self, tmp_workspace):
        (tmp_workspace / "annual_report.pdf").write_bytes(b"%PDF-1.4 fake")
        status = get_workspace_status(tmp_workspace)
        assert status["status"] == "ready"
        assert status["has_materials"] is True
        assert status["materials"] == ["annual_report.pdf"]

    def test_workspace_with_uppercase_pdf_extension(self, tmp_workspace):
        (tmp_workspace / "Annual_Report.PDF").write_bytes(b"%PDF-1.4 fake")
        status = get_workspace_status(tmp_workspace)
        assert status["status"] == "ready"
        assert status["has_materials"] is True
        assert status["materials"] == ["Annual_Report.PDF"]

    def test_partial_completion(self, tmp_workspace):
        (tmp_workspace / "step1_business_analysis.md").write_text("# Step 1")
        (tmp_workspace / "step2_competitive_moat.md").write_text("# Step 2")
        status = get_workspace_status(tmp_workspace)
        assert status["status"] == "in_progress"
        assert status["completed"] == 2
        assert status["steps"][1]["status"] == "completed"
        assert status["steps"][3]["status"] == "pending"

    def test_full_completion(self, tmp_workspace):
        for n in range(1, 8):
            (tmp_workspace / STEP_FILES[n]).write_text(f"# Step {n}")
        status = get_workspace_status(tmp_workspace)
        assert status["status"] == "completed"
        assert status["completed"] == 7

    def test_triage_only_does_not_count_as_core_completion(self, tmp_workspace):
        (tmp_workspace / STEP_FILES[0]).write_text("# Step 0")
        status = get_workspace_status(tmp_workspace)
        assert status["status"] == "triaged"
        assert status["completed"] == 0
        assert status["total"] == 7
        assert status["triage_status"] == "completed"

    def test_pdf_and_steps(self, tmp_workspace):
        (tmp_workspace / "annual_report.pdf").write_bytes(b"%PDF-1.4 fake")
        (tmp_workspace / STEP_FILES[1]).write_text("# Step 1")
        status = get_workspace_status(tmp_workspace)
        assert status["status"] == "in_progress"  # not "ready" since steps started
        assert status["completed"] == 1


class TestSafePath:
    """Tests for _safe_path() path traversal prevention."""

    def test_normal_path(self, tmp_path):
        result = _safe_path(tmp_path, "test.txt")
        assert result is not None
        assert result == (tmp_path / "test.txt").resolve()

    def test_traversal_attack(self, tmp_path):
        result = _safe_path(tmp_path, "../../etc/passwd")
        assert result is None

    def test_absolute_path_escape(self, tmp_path):
        result = _safe_path(tmp_path, "/etc/passwd")
        assert result is None

    def test_null_byte_traversal(self, tmp_path):
        # Path should resolve safely even with tricky characters
        result = _safe_path(tmp_path, "normal.txt")
        assert result is not None

    def test_nested_valid_path(self, tmp_path):
        result = _safe_path(tmp_path, "subdir/file.txt")
        assert result is not None
        assert str(result).endswith("subdir/file.txt")


class TestWorkspacePath:
    def test_rejects_traversal_workspace_name(self):
        assert _workspace_path("../AAPL") is None

    def test_accepts_stock_workspace_name(self):
        result = _workspace_path("600584.SH")
        assert result is not None
        ticker, path = result
        assert ticker == "600584.SH"
        assert path.name == "600584.SH"


# ─── Integration tests with real HTTP server ──────────────────────────


class _TestServer:
    """Lightweight test HTTP server running in a background thread."""

    def __init__(self, workspaces_dir: Path, port: int = 0, auth_token: str = ""):
        from http.server import HTTPServer
        import os

        self.workspaces_dir = workspaces_dir

        # Patch module-level constants
        import web.app as app_module
        self._orig_workspaces = app_module.WORKSPACES
        app_module.WORKSPACES = workspaces_dir

        if auth_token:
            self._orig_token = app_module.AUTH_TOKEN
            app_module.AUTH_TOKEN = auth_token
        else:
            self._orig_token = app_module.AUTH_TOKEN

        self.server = HTTPServer(("localhost", port), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        # Wait for server to be ready
        for _ in range(20):
            try:
                conn = HTTPConnection("localhost", self.port, timeout=1)
                conn.request("GET", "/health")
                resp = conn.getresponse()
                conn.close()
                if resp.status == 200:
                    return
            except (ConnectionRefusedError, OSError):
                time.sleep(0.1)
        raise RuntimeError("Test server did not start")

    def stop(self):
        self.server.shutdown()
        import web.app as app_module
        app_module.WORKSPACES = self._orig_workspaces
        app_module.AUTH_TOKEN = self._orig_token

    def request(self, method, path, body=None, headers=None):
        conn = HTTPConnection("localhost", self.port, timeout=5)
        hdrs = headers or {}
        if body and isinstance(body, dict):
            body = json.dumps(body).encode()
            hdrs.setdefault("Content-Type", "application/json")
        elif body and isinstance(body, bytes):
            pass
        conn.request(method, path, body=body, headers=hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            data = raw.decode()
        except UnicodeDecodeError:
            data = raw  # Binary response (e.g. images)
        return resp.status, data


@pytest.fixture
def web_server(tmp_path):
    """Start a test web server with a temp workspaces directory."""
    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()
    server = _TestServer(ws_dir)
    server.start()
    yield server
    server.stop()


@pytest.fixture
def auth_server(tmp_path):
    """Start a test web server with authentication enabled."""
    ws_dir = tmp_path / "workspaces"
    ws_dir.mkdir()
    server = _TestServer(ws_dir, auth_token="test-secret-token-123")
    server.start()
    yield server
    server.stop()


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_check(self, web_server):
        status, data = web_server.request("GET", "/health")
        assert status == 200
        parsed = json.loads(data)
        assert parsed["status"] == "ok"

    def test_health_no_auth_required(self, auth_server):
        # Health check should work even without auth token
        status, data = auth_server.request("GET", "/health")
        assert status == 200


class TestWorkspacesEndpoint:
    """Tests for GET /api/workspaces."""

    def test_empty_workspaces(self, web_server):
        status, data = web_server.request("GET", "/api/workspaces")
        assert status == 200
        assert json.loads(data) == []

    def test_lists_workspaces(self, web_server):
        # Create a workspace with a step file
        ws = web_server.workspaces_dir / "AAPL"
        ws.mkdir()
        (ws / "step1_business_analysis.md").write_text("# Step 1")

        status, data = web_server.request("GET", "/api/workspaces")
        assert status == 200
        result = json.loads(data)
        assert len(result) == 1
        assert result[0]["ticker"] == "AAPL"
        assert result[0]["completed"] == 1

    def test_ignores_hidden_dirs(self, web_server):
        (web_server.workspaces_dir / ".hidden").mkdir()
        status, data = web_server.request("GET", "/api/workspaces")
        assert status == 200
        assert json.loads(data) == []


class TestWorkspaceStatus:
    """Tests for GET /api/research/{ticker}/status."""

    def test_workspace_not_found(self, web_server):
        status, data = web_server.request("GET", "/api/research/MISSING/status")
        assert status == 404

    def test_workspace_status(self, web_server):
        ws = web_server.workspaces_dir / "AAPL"
        ws.mkdir()
        (ws / "step1_business_analysis.md").write_text("# Step 1")
        (ws / "annual_report.pdf").write_bytes(b"%PDF-1.4 fake")

        status, data = web_server.request("GET", "/api/research/AAPL/status")
        assert status == 200
        result = json.loads(data)
        assert result["ticker"] == "AAPL"
        assert result["completed"] == 1
        assert result["has_materials"] is True
        assert "images" in result


class TestStepEndpoint:
    """Tests for GET /api/research/{ticker}/step/{n}."""

    def test_step0_content(self, web_server):
        ws = web_server.workspaces_dir / "TSLA"
        ws.mkdir()
        (ws / "step0_quick_triage.md").write_text("# Quick Triage\n\nDecision: WATCH")

        status, data = web_server.request("GET", "/api/research/TSLA/step/0")
        assert status == 200
        result = json.loads(data)
        assert result["step"] == 0
        assert "Decision: WATCH" in result["content"]

    def test_step_content(self, web_server):
        ws = web_server.workspaces_dir / "TSLA"
        ws.mkdir()
        (ws / "step2_competitive_moat.md").write_text("# Moat Analysis\n\nWide moat.")

        status, data = web_server.request("GET", "/api/research/TSLA/step/2")
        assert status == 200
        result = json.loads(data)
        assert result["step"] == 2
        assert "Wide moat" in result["content"]

    def test_step_not_found(self, web_server):
        ws = web_server.workspaces_dir / "TSLA"
        ws.mkdir()

        status, data = web_server.request("GET", "/api/research/TSLA/step/1")
        assert status == 404


class TestImageEndpoint:
    """Tests for GET /api/research/{ticker}/image/{name}."""

    def test_serve_image(self, web_server):
        ws = web_server.workspaces_dir / "NVDA"
        ws.mkdir()
        # Create a minimal PNG (1x1 pixel)
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        (ws / "chart.png").write_bytes(png_header)

        status, data = web_server.request("GET", "/api/research/NVDA/image/chart.png")
        assert status == 200
        assert isinstance(data, bytes)  # Binary PNG data
        assert data[:4] == b"\x89PNG"

    def test_serve_uppercase_png_extension(self, web_server):
        ws = web_server.workspaces_dir / "NVDA"
        ws.mkdir()
        png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        (ws / "chart.PNG").write_bytes(png_header)

        status, data = web_server.request("GET", "/api/research/NVDA/image/chart.PNG")

        assert status == 200
        assert data[:4] == b"\x89PNG"

    def test_path_traversal_blocked(self, web_server):
        ws = web_server.workspaces_dir / "NVDA"
        ws.mkdir()

        status, data = web_server.request(
            "GET", "/api/research/NVDA/image/../../etc/passwd"
        )
        assert status == 404

    def test_non_png_rejected(self, web_server):
        ws = web_server.workspaces_dir / "NVDA"
        ws.mkdir()
        (ws / "data.csv").write_text("a,b\n1,2")

        status, data = web_server.request(
            "GET", "/api/research/NVDA/image/data.csv"
        )
        assert status == 404


class TestCreateWorkspace:
    """Tests for POST /api/research."""

    def test_create_workspace(self, web_server):
        body = {"ticker": "MSFT", "notes": "Initial research on cloud"}
        status, data = web_server.request("POST", "/api/research", body=body)
        assert status == 200
        result = json.loads(data)
        assert result["ticker"] == "MSFT"
        assert (web_server.workspaces_dir / "MSFT").is_dir()

        # Check notes file created
        notes = (web_server.workspaces_dir / "MSFT" / "user_notes.md").read_text()
        assert "cloud" in notes

    def test_create_workspace_no_ticker(self, web_server):
        body = {"notes": "Missing ticker"}
        status, data = web_server.request("POST", "/api/research", body=body)
        assert status == 400

    def test_create_workspace_empty_ticker(self, web_server):
        body = {"ticker": "  "}
        status, data = web_server.request("POST", "/api/research", body=body)
        assert status == 400

    def test_rejects_path_traversal_ticker(self, web_server):
        body = {"ticker": "../ESCAPE"}
        status, data = web_server.request("POST", "/api/research", body=body)
        assert status == 400
        assert not (web_server.workspaces_dir.parent / "ESCAPE").exists()


class TestFileUpload:
    """Tests for POST /api/research/{ticker}/upload."""

    def _multipart_body(self, filename: str, content: bytes) -> tuple:
        boundary = "----TestBoundary12345"
        body = (
            f"------TestBoundary12345\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/octet-stream\r\n"
            f"\r\n"
        ).encode() + content + b"\r\n------TestBoundary12345--\r\n"
        headers = {"Content-Type": f"multipart/form-data; boundary=----TestBoundary12345"}
        return body, headers

    def test_upload_pdf(self, web_server):
        ws = web_server.workspaces_dir / "AAPL"
        ws.mkdir()

        body, headers = self._multipart_body("report.pdf", b"%PDF-1.4 fake content")
        status, data = web_server.request(
            "POST", "/api/research/AAPL/upload", body=body, headers=headers
        )
        assert status == 200
        result = json.loads(data)
        assert "report.pdf" in result["uploaded"]
        assert (ws / "report.pdf").exists()

    def test_reject_disallowed_extension(self, web_server):
        ws = web_server.workspaces_dir / "AAPL"
        ws.mkdir()

        body, headers = self._multipart_body("malware.exe", b"MZ\x90\x00")
        status, data = web_server.request(
            "POST", "/api/research/AAPL/upload", body=body, headers=headers
        )
        assert status == 200
        result = json.loads(data)
        assert result["uploaded"] == []
        assert len(result["skipped"]) == 1

    def test_upload_to_nonexistent_workspace(self, web_server):
        body, headers = self._multipart_body("file.pdf", b"content")
        try:
            status, data = web_server.request(
                "POST", "/api/research/MISSING/upload", body=body, headers=headers
            )
            assert status == 404
        except (ConnectionResetError, ConnectionRefusedError):
            # Server may reset connection when workspace not found during upload
            pass

    def test_rejects_path_traversal_workspace(self, web_server):
        body, headers = self._multipart_body("escape.pdf", b"content")
        status, data = web_server.request(
            "POST", "/api/research/../upload", body=body, headers=headers
        )
        assert status == 400
        assert not (web_server.workspaces_dir.parent / "escape.pdf").exists()


class TestAuthentication:
    """Tests for Bearer token authentication."""

    def test_unauthorized_without_token(self, auth_server):
        status, data = auth_server.request("GET", "/api/workspaces")
        assert status == 401

    def test_authorized_with_correct_token(self, auth_server):
        headers = {"Authorization": "Bearer test-secret-token-123"}
        status, data = auth_server.request(
            "GET", "/api/workspaces", headers=headers
        )
        assert status == 200

    def test_wrong_token_rejected(self, auth_server):
        headers = {"Authorization": "Bearer wrong-token"}
        status, data = auth_server.request(
            "GET", "/api/workspaces", headers=headers
        )
        assert status == 401


class TestErrorHandling:
    """Tests for malformed request handling (400 errors)."""

    def test_malformed_content_length_returns_400(self, web_server):
        """Non-numeric Content-Length header should return 400."""
        conn = HTTPConnection("localhost", web_server.port, timeout=5)
        conn.request(
            "POST", "/api/research",
            body=b'{"ticker": "AAPL"}',
            headers={"Content-Type": "application/json", "Content-Length": "abc"},
        )
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        assert resp.status == 400
        result = json.loads(raw)
        assert "Invalid Content-Length" in result.get("error", "")

    def test_malformed_json_body_returns_400(self, web_server):
        """Invalid JSON body should return 400."""
        status, data = web_server.request(
            "POST", "/api/research",
            body=b"this is not json",
            headers={"Content-Type": "application/json"},
        )
        assert status == 400
        result = json.loads(data)
        assert "Invalid JSON" in result.get("error", "")

    def test_serve_uppercase_html_extension(self, web_server):
        """Report endpoint should serve .HTML files (case-insensitive)."""
        ws = web_server.workspaces_dir / "AAPL"
        ws.mkdir()
        (ws / "AAPL_report_20260101.HTML").write_text("<html><body>Report</body></html>")

        status, data = web_server.request(
            "GET", "/api/research/AAPL/report/AAPL_report_20260101.HTML"
        )
        assert status == 200
        assert "Report" in data


class TestNotFound:
    """Tests for 404 handling."""

    def test_unknown_endpoint(self, web_server):
        status, data = web_server.request("GET", "/api/nonexistent")
        assert status == 404

    def test_options_cors(self, web_server):
        status, _ = web_server.request("OPTIONS", "/api/workspaces")
        assert status == 204
