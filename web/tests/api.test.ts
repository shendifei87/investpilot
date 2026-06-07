import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import { setupTestApp, makeMultipartBody } from "./helpers.js";
import type { TestContext } from "./helpers.js";

// ---------------------------------------------------------------------------
// TestHealthEndpoint — mirrors Python (2 tests)
// ---------------------------------------------------------------------------

describe("GET /health", () => {
  let ctx: TestContext;

  beforeEach(() => {
    ctx = setupTestApp();
  });

  afterEach(() => {
    ctx.cleanup();
  });

  it("returns ok status", async () => {
    const res = await ctx.app.request("/health");
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.status).toBe("ok");
  });

  it("works without auth (no token configured)", async () => {
    const res = await ctx.app.request("/health");
    expect(res.status).toBe(200);
  });
});

// ---------------------------------------------------------------------------
// TestWorkspacesEndpoint — mirrors Python (3 tests)
// ---------------------------------------------------------------------------

describe("GET /api/workspaces", () => {
  let ctx: TestContext;

  beforeEach(() => {
    ctx = setupTestApp();
  });

  afterEach(() => {
    ctx.cleanup();
  });

  it("returns empty array when no workspaces", async () => {
    const res = await ctx.app.request("/api/workspaces");
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data).toEqual([]);
  });

  it("lists workspaces with status", async () => {
    const ws = path.join(ctx.workspacesDir, "AAPL");
    fs.mkdirSync(ws);
    fs.writeFileSync(path.join(ws, "step1_business_analysis.md"), "# Step 1");

    const res = await ctx.app.request("/api/workspaces");
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data).toHaveLength(1);
    expect(data[0].ticker).toBe("AAPL");
    expect(data[0].completed).toBe(1);
  });

  it("ignores hidden directories", async () => {
    fs.mkdirSync(path.join(ctx.workspacesDir, ".hidden"));
    const res = await ctx.app.request("/api/workspaces");
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// TestWorkspaceStatus — mirrors Python (2 tests)
// ---------------------------------------------------------------------------

describe("GET /api/research/:ticker/status", () => {
  let ctx: TestContext;

  beforeEach(() => {
    ctx = setupTestApp();
  });

  afterEach(() => {
    ctx.cleanup();
  });

  it("returns 404 for missing workspace", async () => {
    const res = await ctx.app.request("/api/research/MISSING/status");
    expect(res.status).toBe(404);
  });

  it("returns detailed status with images and reports", async () => {
    const ws = path.join(ctx.workspacesDir, "AAPL");
    fs.mkdirSync(ws);
    fs.writeFileSync(path.join(ws, "step1_business_analysis.md"), "# Step 1");
    fs.writeFileSync(path.join(ws, "annual_report.pdf"), "%PDF-1.4 fake");

    const res = await ctx.app.request("/api/research/AAPL/status");
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.ticker).toBe("AAPL");
    expect(data.completed).toBe(1);
    expect(data.has_materials).toBe(true);
    expect("images" in data).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// TestStepEndpoint — mirrors Python (3 tests)
// ---------------------------------------------------------------------------

describe("GET /api/research/:ticker/step/:n", () => {
  let ctx: TestContext;

  beforeEach(() => {
    ctx = setupTestApp();
  });

  afterEach(() => {
    ctx.cleanup();
  });

  it("serves step 0 content", async () => {
    const ws = path.join(ctx.workspacesDir, "TSLA");
    fs.mkdirSync(ws);
    fs.writeFileSync(ws + "/step0_quick_triage.md", "# Quick Triage\n\nDecision: WATCH");

    const res = await ctx.app.request("/api/research/TSLA/step/0");
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.step).toBe(0);
    expect(data.content).toContain("Decision: WATCH");
  });

  it("serves step content", async () => {
    const ws = path.join(ctx.workspacesDir, "TSLA");
    fs.mkdirSync(ws);
    fs.writeFileSync(ws + "/step2_competitive_moat.md", "# Moat Analysis\n\nWide moat.");

    const res = await ctx.app.request("/api/research/TSLA/step/2");
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.step).toBe(2);
    expect(data.content).toContain("Wide moat");
  });

  it("serves step 4 content", async () => {
    const ws = path.join(ctx.workspacesDir, "TSLA");
    fs.mkdirSync(ws);
    fs.writeFileSync(ws + "/step4_assumption_research.md", "# Assumption Research");

    const res = await ctx.app.request("/api/research/TSLA/step/4");
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.step).toBe(4);
    expect(data.content).toContain("Assumption Research");
  });

  it("rejects old split-step aliases", async () => {
    const ws = path.join(ctx.workspacesDir, "TSLA");
    fs.mkdirSync(ws);
    fs.writeFileSync(ws + "/step4_assumption_research.md", "# Assumption Research");

    const res = await ctx.app.request("/api/research/TSLA/step/4a");
    expect(res.status).toBe(404);
  });

  it("returns 404 for missing step file", async () => {
    const ws = path.join(ctx.workspacesDir, "TSLA");
    fs.mkdirSync(ws);

    const res = await ctx.app.request("/api/research/TSLA/step/1");
    expect(res.status).toBe(404);
  });
});

// ---------------------------------------------------------------------------
// TestImageEndpoint — mirrors Python (5 tests)
// ---------------------------------------------------------------------------

describe("GET /api/research/:ticker/image/:name", () => {
  let ctx: TestContext;

  beforeEach(() => {
    ctx = setupTestApp();
  });

  afterEach(() => {
    ctx.cleanup();
  });

  it("serves PNG image", async () => {
    const ws = path.join(ctx.workspacesDir, "NVDA");
    fs.mkdirSync(ws);
    const pngHeader = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...new Uint8Array(20)]);
    fs.writeFileSync(path.join(ws, "chart.png"), pngHeader);

    const res = await ctx.app.request("/api/research/NVDA/image/chart.png");
    expect(res.status).toBe(200);
    const buf = Buffer.from(await res.arrayBuffer());
    expect(buf.slice(0, 4)).toEqual(Buffer.from([0x89, 0x50, 0x4e, 0x47])); // \x89PNG
  });

  it("serves uppercase .PNG extension", async () => {
    const ws = path.join(ctx.workspacesDir, "NVDA");
    fs.mkdirSync(ws);
    const pngHeader = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, ...new Uint8Array(20)]);
    fs.writeFileSync(path.join(ws, "chart.PNG"), pngHeader);

    const res = await ctx.app.request("/api/research/NVDA/image/chart.PNG");
    expect(res.status).toBe(200);
    const buf = Buffer.from(await res.arrayBuffer());
    expect(buf[0]).toBe(0x89);
  });

  it("blocks path traversal", async () => {
    const ws = path.join(ctx.workspacesDir, "NVDA");
    fs.mkdirSync(ws);

    const res = await ctx.app.request("/api/research/NVDA/image/../../etc/passwd");
    expect(res.status).toBe(404);
  });

  it("rejects non-PNG files", async () => {
    const ws = path.join(ctx.workspacesDir, "NVDA");
    fs.mkdirSync(ws);
    fs.writeFileSync(path.join(ws, "data.csv"), "a,b\n1,2");

    const res = await ctx.app.request("/api/research/NVDA/image/data.csv");
    expect(res.status).toBe(404);
  });
});

// ---------------------------------------------------------------------------
// TestCreateWorkspace — mirrors Python (4 tests)
// ---------------------------------------------------------------------------

describe("POST /api/research", () => {
  let ctx: TestContext;

  beforeEach(() => {
    ctx = setupTestApp();
  });

  afterEach(() => {
    ctx.cleanup();
  });

  it("creates workspace with notes", async () => {
    const res = await ctx.app.request("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: "MSFT", notes: "Initial research on cloud" }),
    });
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.ticker).toBe("MSFT");
    expect(fs.existsSync(path.join(ctx.workspacesDir, "MSFT"))).toBe(true);

    const notes = fs.readFileSync(
      path.join(ctx.workspacesDir, "MSFT", "user_notes.md"),
      "utf-8",
    );
    expect(notes).toContain("cloud");
  });

  it("rejects missing ticker", async () => {
    const res = await ctx.app.request("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ notes: "Missing ticker" }),
    });
    expect(res.status).toBe(400);
  });

  it("rejects empty ticker", async () => {
    const res = await ctx.app.request("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: "   " }),
    });
    expect(res.status).toBe(400);
  });

  it("rejects path traversal in ticker", async () => {
    const res = await ctx.app.request("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: "../ESCAPE" }),
    });
    expect(res.status).toBe(400);
    expect(fs.existsSync(path.join(ctx.tmpDir, "ESCAPE"))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// TestFileUpload — mirrors Python (5 tests)
// ---------------------------------------------------------------------------

describe("POST /api/research/:ticker/upload", () => {
  let ctx: TestContext;

  beforeEach(() => {
    ctx = setupTestApp();
  });

  afterEach(() => {
    ctx.cleanup();
  });

  it("uploads a PDF file", async () => {
    const ws = path.join(ctx.workspacesDir, "AAPL");
    fs.mkdirSync(ws);
    const { body, contentType } = makeMultipartBody(
      "report.pdf",
      Buffer.from("%PDF-1.4 fake content"),
    );

    const res = await ctx.app.request("/api/research/AAPL/upload", {
      method: "POST",
      headers: { "Content-Type": contentType, "Content-Length": String(body.length) },
      body,
    });
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.uploaded).toContain("report.pdf");
    expect(fs.existsSync(path.join(ws, "report.pdf"))).toBe(true);
  });

  it("rejects disallowed extension", async () => {
    const ws = path.join(ctx.workspacesDir, "AAPL");
    fs.mkdirSync(ws);
    const { body, contentType } = makeMultipartBody(
      "malware.exe",
      Buffer.from("MZ\x90\x00"),
    );

    const res = await ctx.app.request("/api/research/AAPL/upload", {
      method: "POST",
      headers: { "Content-Type": contentType, "Content-Length": String(body.length) },
      body,
    });
    expect(res.status).toBe(200);
    const data = await res.json();
    expect(data.uploaded).toEqual([]);
    expect(data.skipped).toHaveLength(1);
  });

  it("returns 404 for nonexistent workspace", async () => {
    const { body, contentType } = makeMultipartBody(
      "file.pdf",
      Buffer.from("content"),
    );

    const res = await ctx.app.request("/api/research/MISSING/upload", {
      method: "POST",
      headers: { "Content-Type": contentType, "Content-Length": String(body.length) },
      body,
    });
    expect(res.status).toBe(404);
  });

  it("rejects path traversal in ticker", async () => {
    const { body, contentType } = makeMultipartBody(
      "escape.pdf",
      Buffer.from("content"),
    );

    const res = await ctx.app.request("/api/research/../upload", {
      method: "POST",
      headers: { "Content-Type": contentType, "Content-Length": String(body.length) },
      body,
    });
    // Hono normalizes /../ in paths, so it likely hits a 400 or 404
    expect(res.status).toBeGreaterThanOrEqual(400);
    expect(fs.existsSync(path.join(ctx.tmpDir, "escape.pdf"))).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// TestAuthentication — mirrors Python (3 tests)
// ---------------------------------------------------------------------------

describe("Authentication", () => {
  it("rejects without token when auth is enabled", async () => {
    const ctx = setupTestApp("test-secret-token-123");
    try {
      const res = await ctx.app.request("/api/workspaces");
      expect(res.status).toBe(401);
    } finally {
      ctx.cleanup();
    }
  });

  it("allows with correct token", async () => {
    const ctx = setupTestApp("test-secret-token-123");
    try {
      const res = await ctx.app.request("/api/workspaces", {
        headers: { Authorization: "Bearer test-secret-token-123" },
      });
      expect(res.status).toBe(200);
    } finally {
      ctx.cleanup();
    }
  });

  it("rejects wrong token", async () => {
    const ctx = setupTestApp("test-secret-token-123");
    try {
      const res = await ctx.app.request("/api/workspaces", {
        headers: { Authorization: "Bearer wrong-token" },
      });
      expect(res.status).toBe(401);
    } finally {
      ctx.cleanup();
    }
  });
});

// ---------------------------------------------------------------------------
// TestErrorHandling — mirrors Python (3 tests)
// ---------------------------------------------------------------------------

describe("Error handling", () => {
  let ctx: TestContext;

  beforeEach(() => {
    ctx = setupTestApp();
  });

  afterEach(() => {
    ctx.cleanup();
  });

  it("returns 400 for malformed Content-Length", async () => {
    const res = await ctx.app.request("/api/research", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Content-Length": "abc",
      },
      body: JSON.stringify({ ticker: "AAPL" }),
    });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error).toContain("Invalid Content-Length");
  });

  it("returns 400 for malformed JSON body", async () => {
    const res = await ctx.app.request("/api/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "this is not json",
    });
    expect(res.status).toBe(400);
    const data = await res.json();
    expect(data.error).toContain("Invalid JSON");
  });

  it("serves uppercase .HTML report extension", async () => {
    const ws = path.join(ctx.workspacesDir, "AAPL");
    fs.mkdirSync(ws);
    fs.writeFileSync(
      path.join(ws, "AAPL_report_20260101.HTML"),
      "<html><body>Report</body></html>",
    );

    const res = await ctx.app.request("/api/research/AAPL/report/AAPL_report_20260101.HTML");
    expect(res.status).toBe(200);
    const text = await res.text();
    expect(text).toContain("Report");
  });
});

// ---------------------------------------------------------------------------
// TestNotFound — mirrors Python (2 tests)
// ---------------------------------------------------------------------------

describe("404 handling", () => {
  let ctx: TestContext;

  beforeEach(() => {
    ctx = setupTestApp();
  });

  afterEach(() => {
    ctx.cleanup();
  });

  it("returns 404 for unknown endpoint", async () => {
    const res = await ctx.app.request("/api/nonexistent");
    expect(res.status).toBe(404);
  });

  it("handles OPTIONS with CORS", async () => {
    const res = await ctx.app.request("/api/workspaces", { method: "OPTIONS" });
    // Hono cors middleware returns 204 for OPTIONS
    expect(res.status).toBe(204);
  });
});
