import type { MiddlewareHandler } from "hono";
import { AUTH_TOKEN, timingSafeEqual } from "../config.js";

/**
 * Bearer token authentication middleware.
 *
 * - If `INVESTPILOT_TOKEN` env var is empty → open access (localhost-only mode).
 * - If set → requires `Authorization: Bearer <token>` header.
 * - Uses timing-safe comparison to prevent timing attacks.
 */
export const authMiddleware: MiddlewareHandler = async (c, next) => {
  // No token configured = open access
  if (!AUTH_TOKEN) {
    return next();
  }

  const authHeader = c.req.header("Authorization") ?? "";
  if (authHeader.startsWith("Bearer ")) {
    const token = authHeader.slice(7);
    if (timingSafeEqual(token, AUTH_TOKEN)) {
      return next();
    }
  }

  return c.json({ error: "Unauthorized" }, 401);
};
