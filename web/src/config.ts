import { fileURLToPath } from "node:url";
import path from "node:path";
import crypto from "node:crypto";
import fs from "node:fs";

// ---------------------------------------------------------------------------
// Paths
// ---------------------------------------------------------------------------

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
/** Project root (two levels up from web/src/) */
const PROJECT_ROOT = path.resolve(__dirname, "..", "..");
/** Web static assets directory */
const _WEB_DIR = path.resolve(__dirname, "..", "public");

// Use `let` for test-overridable values (ES module live bindings)
export let WORKSPACES_DIR =
  process.env.WORKSPACES_DIR ?? path.join(PROJECT_ROOT, "workspaces");
export let AUTH_TOKEN = process.env.INVESTPILOT_TOKEN ?? "";
export let WEB_DIR = _WEB_DIR;
export let CORS_ORIGIN = process.env.INVESTPILOT_CORS_ORIGIN ?? "";

/** Reset config for testing — override WORKSPACES_DIR and AUTH_TOKEN */
export function _testOverride(overrides: {
  WORKSPACES_DIR?: string;
  AUTH_TOKEN?: string;
  CORS_ORIGIN?: string;
}) {
  if (overrides.WORKSPACES_DIR !== undefined) WORKSPACES_DIR = overrides.WORKSPACES_DIR;
  if (overrides.AUTH_TOKEN !== undefined) AUTH_TOKEN = overrides.AUTH_TOKEN;
  if (overrides.CORS_ORIGIN !== undefined) CORS_ORIGIN = overrides.CORS_ORIGIN;
}

// ---------------------------------------------------------------------------
// Step definitions (single source: config/step_contracts.json)
// ---------------------------------------------------------------------------

interface StepContract {
  id: string;
  name: string;
  primary_artifact: string;
}

interface StepContractsConfig {
  core_steps: string[];
  steps: StepContract[];
}

function loadStepContracts(): StepContractsConfig {
  const STEP_CONTRACTS_PATH = path.join(PROJECT_ROOT, "config", "step_contracts.json");
  try {
    if (!fs.existsSync(STEP_CONTRACTS_PATH)) {
      throw new Error(
        `step_contracts.json not found at ${STEP_CONTRACTS_PATH}. ` +
        "Ensure the config/ directory is present in the project root.",
      );
    }
    const raw = fs.readFileSync(STEP_CONTRACTS_PATH, "utf-8");
    const data = JSON.parse(raw) as StepContractsConfig;
    if (!Array.isArray(data.steps)) {
      throw new Error("step_contracts.json must contain a 'steps' array");
    }
    return data;
  } catch (err) {
    if (err instanceof SyntaxError) {
      throw new Error(
        `Failed to parse step_contracts.json: ${err.message}. ` +
        "Check for JSON syntax errors.",
      );
    }
    throw err;
  }
}

const STEP_CONTRACTS_DATA = loadStepContracts();

export type StepId = string;
export const STEP_ORDER = STEP_CONTRACTS_DATA.steps.map((step) => step.id);
export const STEP_FILES: Record<StepId, string> = Object.fromEntries(
  STEP_CONTRACTS_DATA.steps.map((step) => [step.id, step.primary_artifact]),
);
export const STEP_NAMES: Record<StepId, string> = Object.fromEntries(
  STEP_CONTRACTS_DATA.steps.map((step) => [step.id, step.name]),
);

export const CORE_STEP_IDS = STEP_CONTRACTS_DATA.core_steps;
export const DISPLAY_STEP_IDS = STEP_ORDER;

export function normalizeStepId(raw: string): StepId | null {
  const key = raw.trim().toLowerCase();
  return (STEP_ORDER as readonly string[]).includes(key) ? (key as StepId) : null;
}

// ---------------------------------------------------------------------------
// Security configuration
// ---------------------------------------------------------------------------

export const MAX_UPLOAD_BYTES = 50 * 1024 * 1024; // 50 MB
export const ALLOWED_UPLOAD_EXT = new Set([".pdf", ".csv", ".json", ".md"]);

/** Regex for workspace (ticker) names — uppercase alphanumeric + limited punctuation */
export const WORKSPACE_NAME_RE = /^[A-Z0-9][A-Z0-9._-]{0,63}$/;

/** Extensions considered as "materials" (user-provided files) */
export const MATERIAL_EXTS = new Set([".pdf"]);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Timing-safe string comparison (mirrors Python's `secrets.compare_digest`).
 */
export function timingSafeEqual(a: string, b: string): boolean {
  const bufA = Buffer.from(a);
  const bufB = Buffer.from(b);
  if (bufA.length !== bufB.length) {
    // Compare bufA against itself to keep constant time, then return false
    crypto.timingSafeEqual(bufA, bufA);
    return false;
  }
  return crypto.timingSafeEqual(bufA, bufB);
}
