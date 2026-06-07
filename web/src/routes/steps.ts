import { Hono } from "hono";
import fs from "node:fs";
import path from "node:path";
import { normalizeStepId, STEP_FILES } from "../config.js";
import { workspacePath } from "../services/workspace.js";

const steps = new Hono();

/**
 * GET /api/research/:ticker/step/:n
 * Return markdown content for a specific step (0-9).
 */
steps.get("/api/research/:ticker/step/:n", (c) => {
  const tickerParam = c.req.param("ticker");
  const stepParam = c.req.param("n");
  const step = normalizeStepId(stepParam);

  const resolved = workspacePath(tickerParam);
  if (!resolved || step === null) {
    return c.json({ error: "Step not found" }, 404);
  }

  const { ticker, wsPath } = resolved;
  const stepFilename = STEP_FILES[step];
  if (!stepFilename) {
    return c.json({ error: "Step not found" }, 404);
  }

  const stepFile = path.join(wsPath, stepFilename);
  if (!fs.existsSync(stepFile)) {
    return c.json({ error: "Step not found" }, 404);
  }

  const content = fs.readFileSync(stepFile, "utf-8");
  const responseStep: string | number = /^\d+$/.test(step) ? Number(step) : step;
  return c.json({ ticker, step: responseStep, content });
});

export default steps;
