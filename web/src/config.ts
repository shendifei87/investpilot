import { fileURLToPath } from "node:url";
import path from "node:path";
import crypto from "node:crypto";

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
// Step definitions (mirrors Python app.py)
// ---------------------------------------------------------------------------

export const STEP_FILES: Record<number, string> = {
  0: "step0_quick_triage.md",
  1: "step1_business_analysis.md",
  2: "step2_competitive_moat.md",
  3: "step3_marginal_changes.md",
  4: "step4_quantitative_model.md",
  5: "step5_rrr_strategy.md",
  6: "step6_auditing.md",
  7: "step7_research_director_review.md",
};

export const STEP_NAMES: Record<number, string> = {
  0: "Quick Triage",
  1: "Business Deep Dive",
  2: "Competitive Moat",
  3: "Marginal Changes & Expectation Gap",
  4: "Quantitative Model & Simulation",
  5: "RRR & Trading Strategy",
  6: "Auditing & Quality Control",
  7: "Research Director Review",
};

export const CORE_STEP_NUMBERS = [1, 2, 3, 4, 5, 6, 7] as const;
export const DISPLAY_STEP_NUMBERS = Object.keys(STEP_FILES)
  .map(Number)
  .sort((a, b) => a - b);

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
