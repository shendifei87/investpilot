import type { MiddlewareHandler } from "hono";
import { MAX_UPLOAD_BYTES } from "../config.js";

/**
 * Reject requests with Content-Length exceeding the upload limit.
 * Applied only to POST routes that accept body data.
 */
export const uploadLimitMiddleware: MiddlewareHandler = async (c, next) => {
  const contentLength = parseInt(c.req.header("Content-Length") ?? "0", 10);
  if (isNaN(contentLength)) {
    return c.json({ error: "Invalid Content-Length" }, 400);
  }
  if (contentLength > MAX_UPLOAD_BYTES) {
    return c.json({ error: "Request too large" }, 413);
  }
  return next();
};
