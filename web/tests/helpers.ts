/**
 * Test utilities for InvestPilot web tests.
 *
 * Uses config._testOverride() to inject temp workspaces dir.
 * Since config exports `let` bindings, all downstream modules
 * that import WORKSPACES_DIR see the patched value in real time.
 */
import { Hono } from "hono";
import { cors } from "hono/cors";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

import { _testOverride } from "../src/config.js";
import { authMiddleware } from "../src/middleware/auth.js";
import { uploadLimitMiddleware } from "../src/middleware/uploadLimit.js";
import healthRoutes from "../src/routes/health.js";
import workspaceRoutes from "../src/routes/workspaces.js";
import stepRoutes from "../src/routes/steps.js";
import fileRoutes from "../src/routes/files.js";
import researchRoutes from "../src/routes/research.js";

export interface TestContext {
  tmpDir: string;
  workspacesDir: string;
  app: Hono;
  cleanup: () => void;
}

/**
 * Create a temp workspaces dir and a fully-wired Hono app.
 */
export function setupTestApp(authToken = ""): TestContext {
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), "investpilot-test-"));
  const workspacesDir = path.join(tmpDir, "workspaces");
  fs.mkdirSync(workspacesDir, { recursive: true });

  // Patch config — all imports in routes/services see the new value
  _testOverride({ WORKSPACES_DIR: workspacesDir, AUTH_TOKEN: authToken });

  const app = new Hono();
  app.use("*", cors({ origin: "*" }));
  app.route("/", healthRoutes);
  app.use("*", authMiddleware);
  app.use("/api/research", uploadLimitMiddleware);
  app.use("/api/research/*", uploadLimitMiddleware);
  app.route("/", workspaceRoutes);
  app.route("/", stepRoutes);
  app.route("/", fileRoutes);
  app.route("/", researchRoutes);
  app.notFound((c) => c.json({ error: "Not found" }, 404));

  const cleanup = () => {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    // Reset to defaults
    _testOverride({
      WORKSPACES_DIR: path.resolve(
        path.dirname(new URL(import.meta.url).pathname),
        "..",
        "..",
        "workspaces",
      ),
      AUTH_TOKEN: "",
    });
  };

  return { tmpDir, workspacesDir, app, cleanup };
}

// ---------------------------------------------------------------------------
// Multipart helper
// ---------------------------------------------------------------------------

export function makeMultipartBody(
  filename: string,
  content: Buffer,
): { body: Buffer; contentType: string } {
  const boundary = "----TestBoundary12345";
  const header = Buffer.from(
    `------TestBoundary12345\r\n` +
      `Content-Disposition: form-data; name="file"; filename="${filename}"\r\n` +
      `Content-Type: application/octet-stream\r\n` +
      `\r\n`,
  );
  const footer = Buffer.from(`\r\n------TestBoundary12345--\r\n`);
  const body = Buffer.concat([header, content, footer]);
  return {
    body,
    contentType: `multipart/form-data; boundary=----TestBoundary12345`,
  };
}
