import { Hono } from "hono";
import { WORKSPACES_DIR } from "../config.js";

const health = new Hono();

health.get("/health", (c) => {
  return c.json({ status: "ok" });
});

export default health;
