import { Hono } from "hono";
import { cors } from "hono/cors";
import { serve } from "@hono/node-server";
import fs from "node:fs";
import path from "node:path";

import {
  AUTH_TOKEN,
  CORS_ORIGIN,
  MAX_UPLOAD_BYTES,
  WEB_DIR,
  WORKSPACES_DIR,
} from "./config.js";
import { authMiddleware } from "./middleware/auth.js";
import { uploadLimitMiddleware } from "./middleware/uploadLimit.js";
import healthRoutes from "./routes/health.js";
import workspaceRoutes from "./routes/workspaces.js";
import stepRoutes from "./routes/steps.js";
import fileRoutes from "./routes/files.js";
import researchRoutes from "./routes/research.js";

// ---------------------------------------------------------------------------
// App
// ---------------------------------------------------------------------------

const app = new Hono();

// CORS — dynamic origin matching Python behavior
app.use(
  "*",
  cors({
    origin: (_origin, c) => {
      if (CORS_ORIGIN) return CORS_ORIGIN;
      const url = new URL(c.req.url);
      return `http://localhost:${url.port}`;
    },
    allowHeaders: ["Authorization", "Content-Type"],
  }),
);

// Health check — no auth required
app.route("/", healthRoutes);

// Auth middleware for all other routes (runs after health, before everything else)
app.use("*", authMiddleware);

// Upload size limit for POST routes — before research routes are registered
app.use("/api/research", uploadLimitMiddleware);
app.use("/api/research/*", uploadLimitMiddleware);

// Serve index.html at root
app.get("/", (c) => {
  const htmlPath = path.join(WEB_DIR, "index.html");
  if (!fs.existsSync(htmlPath)) {
    return c.json({ error: "index.html not found" }, 500);
  }
  const html = fs.readFileSync(htmlPath, "utf-8");
  return c.html(html);
});

// API routes
app.route("/", workspaceRoutes);
app.route("/", stepRoutes);
app.route("/", fileRoutes);
app.route("/", researchRoutes);

// 404 catch-all
app.notFound((c) => {
  return c.json({ error: "Not found" }, 404);
});

// ---------------------------------------------------------------------------
// Server startup
// ---------------------------------------------------------------------------

const port = parseInt(process.argv[2] ?? "8080", 10);

const authStatus = AUTH_TOKEN
  ? "enabled (INVESTPILOT_TOKEN set)"
  : "disabled (set INVESTPILOT_TOKEN env var to enable)";

console.log(`InvestPilot Dashboard: http://localhost:${port}`);
console.log(`Authentication: ${authStatus}`);
console.log(`Max upload size: ${MAX_UPLOAD_BYTES / (1024 * 1024)} MB`);
console.log(`Workspaces: ${WORKSPACES_DIR}`);
console.log(`Health check: http://localhost:${port}/health`);

serve({ fetch: app.fetch, port }, (info) => {
  console.log(`Server listening on http://localhost:${info.port}`);
});
