import { describe, it, expect, beforeEach, afterEach } from "vitest";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import {
  safePath,
  workspacePath,
  getWorkspaceStatus,
  listWorkspaceDirs,
} from "../src/services/workspace.js";
import { STEP_FILES } from "../src/config.js";
import { _testOverride } from "../src/config.js";

// ---------------------------------------------------------------------------
// TestGetWorkspaceStatus — mirrors Python TestGetWorkspaceStatus (8 tests)
// ---------------------------------------------------------------------------

describe("getWorkspaceStatus", () => {
  let tmpDir: string;
  let wsDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ip-ws-test-"));
    wsDir = path.join(tmpDir, "workspaces", "TEST");
    fs.mkdirSync(wsDir, { recursive: true });
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("returns empty status for empty workspace", () => {
    const status = getWorkspaceStatus(wsDir);
    expect(status.status).toBe("empty");
    expect(status.completed).toBe(0);
    expect(status.total).toBe(7);
    expect(status.triage_status).toBe("pending");
    expect(status.steps[0].file).toBe("step0_quick_triage.md");
    expect(status.has_materials).toBe(false);
  });

  it("detects PDF materials (lowercase extension)", () => {
    fs.writeFileSync(path.join(wsDir, "annual_report.pdf"), "%PDF-1.4 fake");
    const status = getWorkspaceStatus(wsDir);
    expect(status.status).toBe("ready");
    expect(status.has_materials).toBe(true);
    expect(status.materials).toContain("annual_report.pdf");
  });

  it("detects PDF materials (uppercase extension)", () => {
    fs.writeFileSync(path.join(wsDir, "Annual_Report.PDF"), "%PDF-1.4 fake");
    const status = getWorkspaceStatus(wsDir);
    expect(status.status).toBe("ready");
    expect(status.has_materials).toBe(true);
    expect(status.materials).toContain("Annual_Report.PDF");
  });

  it("tracks partial completion", () => {
    fs.writeFileSync(path.join(wsDir, "step1_business_analysis.md"), "# Step 1");
    fs.writeFileSync(path.join(wsDir, "step2_competitive_moat.md"), "# Step 2");
    const status = getWorkspaceStatus(wsDir);
    expect(status.status).toBe("in_progress");
    expect(status.completed).toBe(2);
    expect(status.steps[1].status).toBe("completed");
    expect(status.steps[3].status).toBe("pending");
  });

  it("tracks full completion", () => {
    for (let n = 1; n <= 7; n++) {
      fs.writeFileSync(path.join(wsDir, STEP_FILES[n]!), `# Step ${n}`);
    }
    const status = getWorkspaceStatus(wsDir);
    expect(status.status).toBe("completed");
    expect(status.completed).toBe(7);
  });

  it("triage only does not count as core completion", () => {
    fs.writeFileSync(path.join(wsDir, STEP_FILES[0]!), "# Step 0");
    const status = getWorkspaceStatus(wsDir);
    expect(status.status).toBe("triaged");
    expect(status.completed).toBe(0);
    expect(status.total).toBe(7);
    expect(status.triage_status).toBe("completed");
  });

  it("steps take priority over materials", () => {
    fs.writeFileSync(path.join(wsDir, "annual_report.pdf"), "%PDF-1.4 fake");
    fs.writeFileSync(path.join(wsDir, STEP_FILES[1]!), "# Step 1");
    const status = getWorkspaceStatus(wsDir);
    expect(status.status).toBe("in_progress"); // not "ready"
    expect(status.completed).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// TestSafePath — mirrors Python TestSafePath (5 tests)
// ---------------------------------------------------------------------------

describe("safePath", () => {
  let tmpDir: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ip-safe-test-"));
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it("resolves normal paths", () => {
    const result = safePath(tmpDir, "test.txt");
    expect(result).not.toBeNull();
    expect(result).toBe(path.resolve(tmpDir, "test.txt"));
  });

  it("blocks traversal attacks", () => {
    const result = safePath(tmpDir, "../../etc/passwd");
    expect(result).toBeNull();
  });

  it("blocks absolute path escape", () => {
    const result = safePath(tmpDir, "/etc/passwd");
    expect(result).toBeNull();
  });

  it("allows normal filenames safely", () => {
    const result = safePath(tmpDir, "normal.txt");
    expect(result).not.toBeNull();
  });

  it("allows nested valid paths", () => {
    const result = safePath(tmpDir, "subdir/file.txt");
    expect(result).not.toBeNull();
    expect(result!.endsWith("subdir/file.txt")).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// TestWorkspacePath — mirrors Python TestWorkspacePath (2 tests)
// ---------------------------------------------------------------------------

describe("workspacePath", () => {
  let tmpDir: string;
  let wsParent: string;

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "ip-wspath-test-"));
    wsParent = path.join(tmpDir, "workspaces");
    fs.mkdirSync(wsParent, { recursive: true });
    _testOverride({ WORKSPACES_DIR: wsParent });
  });

  afterEach(() => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    _testOverride({ WORKSPACES_DIR: "" });
  });

  it("rejects traversal workspace name", () => {
    expect(workspacePath("../AAPL")).toBeNull();
  });

  it("accepts stock workspace names with dot suffix", () => {
    const result = workspacePath("600584.SH");
    expect(result).not.toBeNull();
    expect(result!.ticker).toBe("600584.SH");
    expect(path.basename(result!.wsPath)).toBe("600584.SH");
  });
});
