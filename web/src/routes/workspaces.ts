import { Hono } from "hono";
import fs from "node:fs";
import path from "node:path";
import {
  getWorkspaceStatus,
  listReports,
  listImages,
  listWorkspaceDirs,
  workspacePath,
} from "../services/workspace.js";
import { WORKSPACES_DIR } from "../config.js";

const workspaces = new Hono();

/**
 * GET /api/workspaces
 * List all workspaces with status metadata.
 */
workspaces.get("/api/workspaces", (c) => {
  const dirs = listWorkspaceDirs();
  const results = dirs.map((dirName) => {
    const wsDir = path.join(WORKSPACES_DIR, dirName);
    const status = getWorkspaceStatus(wsDir);
    return {
      ticker: dirName,
      path: wsDir,
      reports: listReports(wsDir),
      ...status,
    };
  });

  return c.json(results);
});

/**
 * GET /api/research/:ticker/status
 * Detailed workspace status including images and reports.
 */
workspaces.get("/api/research/:ticker/status", (c) => {
  const tickerParam = c.req.param("ticker");
  const resolved = workspacePath(tickerParam);
  if (!resolved) {
    return c.json({ error: "Workspace not found" }, 404);
  }

  const { ticker, wsPath } = resolved;
  if (!fs.existsSync(wsPath)) {
    return c.json({ error: "Workspace not found" }, 404);
  }

  const status = getWorkspaceStatus(wsPath);
  return c.json({
    ticker,
    images: listImages(wsPath),
    reports: listReports(wsPath),
    ...status,
  });
});

export default workspaces;
