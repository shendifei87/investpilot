import fs from "node:fs";
import path from "node:path";
import {
  WORKSPACES_DIR,
  STEP_FILES,
  STEP_NAMES,
  CORE_STEP_IDS,
  DISPLAY_STEP_IDS,
  type StepId,
  WORKSPACE_NAME_RE,
  MATERIAL_EXTS,
} from "../config.js";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface StepInfo {
  name: string;
  file: string;
  status: "completed" | "pending";
}

export interface WorkspaceStatus {
  has_materials: boolean;
  materials: string[];
  steps: Record<string, StepInfo>;
  completed: number;
  total: number;
  triage_status: string;
  status: "empty" | "ready" | "triaged" | "in_progress" | "completed";
}

export interface ResolvedWorkspace {
  ticker: string;
  wsPath: string;
}

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

/**
 * Resolve a user-supplied path and verify it stays under the base directory.
 * Returns `null` if the path escapes base (traversal prevention).
 */
export function safePath(base: string, userPath: string): string | null {
  const resolved = path.resolve(base, userPath);
  const baseResolved = path.resolve(base);
  if (resolved.startsWith(baseResolved + path.sep) || resolved === baseResolved) {
    return resolved;
  }
  return null;
}

/**
 * Validate and resolve a workspace path for a URL/body ticker.
 * Returns `{ ticker, wsPath }` or `null` if invalid.
 */
export function workspacePath(ticker: string): ResolvedWorkspace | null {
  const normalized = decodeURIComponent(ticker).trim().toUpperCase();
  if (!WORKSPACE_NAME_RE.test(normalized)) {
    return null;
  }
  const wsPath = safePath(WORKSPACES_DIR, normalized);
  if (wsPath === null) {
    return null;
  }
  return { ticker: normalized, wsPath };
}

// ---------------------------------------------------------------------------
// Workspace status
// ---------------------------------------------------------------------------

/**
 * Return user-provided material files in a workspace (case-insensitive extension).
 */
export function workspaceMaterialFiles(wsDir: string): string[] {
  if (!fs.existsSync(wsDir)) return [];
  try {
    return fs
      .readdirSync(wsDir)
      .filter((name) => {
        const stat = fs.statSync(path.join(wsDir, name));
        return stat.isFile() && MATERIAL_EXTS.has(path.extname(name).toLowerCase());
      });
  } catch {
    return [];
  }
}

/**
 * Scan a workspace directory and compute its status.
 * Mirrors Python `get_workspace_status()` exactly.
 */
export function getWorkspaceStatus(wsDir: string): WorkspaceStatus {
  const materialFiles = workspaceMaterialFiles(wsDir);
  const hasMaterials = materialFiles.length > 0;
  const steps: Record<string, StepInfo> = {};
  let completed = 0;

  for (const n of DISPLAY_STEP_IDS) {
    const fileName = STEP_FILES[n];
    const done = fs.existsSync(path.join(wsDir, fileName));
    if (CORE_STEP_IDS.includes(n as (typeof CORE_STEP_IDS)[number]) && done) {
      completed++;
    }
    steps[n] = {
      name: STEP_NAMES[n as StepId],
      file: fileName,
      status: done ? "completed" : "pending",
    };
  }

  const triageDone = steps["0"]!.status === "completed";
  let status: WorkspaceStatus["status"] = "empty";
  if (completed > 0) status = "in_progress";
  if (completed === CORE_STEP_IDS.length) status = "completed";
  else if (triageDone && completed === 0) status = "triaged";
  else if (hasMaterials && completed === 0) status = "ready";

  return {
    has_materials: hasMaterials,
    materials: materialFiles,
    steps,
    completed,
    total: CORE_STEP_IDS.length,
    triage_status: steps["0"]!.status,
    status,
  };
}

/**
 * List HTML reports in a workspace directory, newest first.
 */
export function listReports(wsDir: string): string[] {
  if (!fs.existsSync(wsDir)) return [];
  try {
    return fs
      .readdirSync(wsDir)
      .filter((f) => /_report_.*\.html$/i.test(f))
      .sort()
      .reverse();
  } catch {
    return [];
  }
}

/**
 * List PNG images in a workspace directory.
 */
export function listImages(wsDir: string): string[] {
  if (!fs.existsSync(wsDir)) return [];
  try {
    return fs.readdirSync(wsDir).filter((f) => path.extname(f).toLowerCase() === ".png");
  } catch {
    return [];
  }
}

/**
 * List all workspace directories (non-hidden).
 */
export function listWorkspaceDirs(): string[] {
  if (!fs.existsSync(WORKSPACES_DIR)) return [];
  try {
    return fs
      .readdirSync(WORKSPACES_DIR)
      .filter((name) => {
        const fullPath = path.join(WORKSPACES_DIR, name);
        return (
          !name.startsWith(".") &&
          fs.statSync(fullPath).isDirectory()
        );
      })
      .sort();
  } catch {
    return [];
  }
}
