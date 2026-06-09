import { Hono } from "hono";
import fs from "node:fs";
import path from "node:path";
import { workspacePath } from "../services/workspace.js";
import { parseMultipartBuffer, processUploadedFiles } from "../services/multipart.js";

const research = new Hono();

/**
 * POST /api/research
 * Create a new workspace with optional notes.
 *
 * Body: { ticker: string, notes?: string }
 */
research.post("/api/research", async (c) => {
  let body: { ticker?: string; notes?: string };
  try {
    body = await c.req.json();
  } catch {
    return c.json({ error: "Invalid JSON" }, 400);
  }

  const ticker = (body.ticker ?? "").trim().toUpperCase();
  const notes = (body.notes ?? "").trim();

  if (!ticker) {
    return c.json({ error: "Ticker is required" }, 400);
  }

  const resolved = workspacePath(ticker);
  if (!resolved) {
    return c.json({ error: "Invalid ticker" }, 400);
  }

  const { ticker: normTicker, wsPath } = resolved;
  fs.mkdirSync(wsPath, { recursive: true });

  if (notes) {
    const notesPath = path.join(wsPath, "user_notes.md");
    if (!fs.existsSync(notesPath)) {
      fs.writeFileSync(notesPath, `# User Notes\n\n${notes}\n`, "utf-8");
    }
  }

  return c.json({
    ticker: normTicker,
    path: wsPath,
    message: `Workspace created at ${wsPath}. Please add annual reports and research PDFs.`,
  });
});

/**
 * POST /api/research/:ticker/upload
 * Multipart file upload into the workspace.
 *
 * Reads the full body as ArrayBuffer, then parses multipart manually.
 * Allowed extensions: .pdf, .csv, .json, .md.
 * Skips files that already exist (no overwrite).
 */
research.post("/api/research/:ticker/upload", async (c) => {
  const tickerParam = c.req.param("ticker");
  const resolved = workspacePath(tickerParam);
  if (!resolved) {
    return c.json({ error: "Invalid ticker" }, 400);
  }

  const { wsPath } = resolved;
  if (!fs.existsSync(wsPath)) {
    return c.json({ error: "Workspace not found" }, 404);
  }

  const contentType = c.req.header("Content-Type") ?? "";
  const arrayBuffer = await c.req.arrayBuffer();
  const buffer = Buffer.from(arrayBuffer);

  const files = parseMultipartBuffer(buffer, contentType);
  const result = processUploadedFiles(files, wsPath, fs);

  return c.json(result);
});

export default research;
