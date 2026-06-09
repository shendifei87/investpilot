import { Hono } from "hono";
import fs from "node:fs";
import path from "node:path";
import { workspacePath, safePath } from "../services/workspace.js";

const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50 MB

const files = new Hono();

/**
 * GET /api/research/:ticker/image/:name
 * Serve a PNG image from the workspace.
 */
files.get("/api/research/:ticker/image/:name", (c) => {
  const tickerParam = c.req.param("ticker");
  const imgName = c.req.param("name");

  const resolved = workspacePath(tickerParam);
  if (!resolved) {
    return c.json({ error: "Not found" }, 404);
  }

  const { wsPath } = resolved;
  const decodedName = decodeURIComponent(imgName);
  const imgPath = safePath(wsPath, decodedName);

  if (
    !imgPath ||
    !fs.existsSync(imgPath) ||
    path.extname(imgPath).toLowerCase() !== ".png"
  ) {
    return c.json({ error: "Not found" }, 404);
  }

  const stat = fs.statSync(imgPath);
  if (stat.size > MAX_FILE_SIZE) {
    return c.json({ error: "File too large" }, 413);
  }

  const data = fs.readFileSync(imgPath);
  return new Response(data, {
    status: 200,
    headers: { "Content-Type": "image/png" },
  });
});

/**
 * GET /api/research/:ticker/report/:name
 * Serve an HTML report from the workspace.
 */
files.get("/api/research/:ticker/report/:name", (c) => {
  const tickerParam = c.req.param("ticker");
  const reportName = c.req.param("name");

  const resolved = workspacePath(tickerParam);
  if (!resolved) {
    return c.json({ error: "Not found" }, 404);
  }

  const { wsPath } = resolved;
  const decodedName = decodeURIComponent(reportName);
  const filePath = safePath(wsPath, decodedName);

  if (
    !filePath ||
    !fs.existsSync(filePath) ||
    path.extname(filePath).toLowerCase() !== ".html"
  ) {
    return c.json({ error: "Not found" }, 404);
  }

  const stat = fs.statSync(filePath);
  if (stat.size > MAX_FILE_SIZE) {
    return c.json({ error: "File too large" }, 413);
  }

  const data = fs.readFileSync(filePath);
  return new Response(data, {
    status: 200,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
});

export default files;
