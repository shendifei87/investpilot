import path from "node:path";
import { ALLOWED_UPLOAD_EXT } from "../config.js";

export interface UploadResult {
  uploaded: string[];
  skipped: Array<{ name: string; reason: string }>;
}

/**
 * Parse multipart form data from a raw buffer.
 *
 * This mirrors the Python `_parse_multipart` hand-rolled parser exactly —
 * no external streaming dependencies needed. Works with Hono's `arrayBuffer()`.
 */
export function parseMultipartBuffer(
  buffer: Buffer,
  contentType: string,
): Array<{ filename: string; data: Buffer }> {
  const boundaryMatch = contentType.match(/boundary=(.+?)(?:;|$)/);
  if (!boundaryMatch) return [];

  const boundary = boundaryMatch[1]!.trim();
  const boundaryBytes = Buffer.from(`--${boundary}`);
  const files: Array<{ filename: string; data: Buffer }> = [];

  // Split by boundary
  let offset = buffer.indexOf(boundaryBytes);
  if (offset === -1) return [];

  while (true) {
    // Find the next boundary
    const partStart = offset + boundaryBytes.length;
    if (partStart >= buffer.length) break;

    // Skip \r\n after boundary
    let pos = partStart;
    if (pos < buffer.length && buffer[pos] === 0x0d) pos++; // \r
    if (pos < buffer.length && buffer[pos] === 0x0a) pos++; // \n

    // Find end of this part (next boundary)
    const nextBoundary = buffer.indexOf(boundaryBytes, pos);
    if (nextBoundary === -1) break;

    const partData = buffer.subarray(pos, nextBoundary);

    // Remove trailing \r\n before next boundary
    let end = partData.length;
    if (end >= 2 && partData[end - 2] === 0x0d && partData[end - 1] === 0x0a) {
      end -= 2;
    }

    const part = partData.subarray(0, end);

    // Split headers from body at \r\n\r\n
    const headerEnd = part.indexOf("\r\n\r\n");
    if (headerEnd === -1) {
      offset = nextBoundary;
      continue;
    }

    const headerSection = part.subarray(0, headerEnd).toString("utf-8");
    const body = part.subarray(headerEnd + 4);

    // Extract filename from Content-Disposition header
    const filenameMatch = headerSection.match(
      /filename="([^"]+)"/,
    );
    if (filenameMatch) {
      files.push({ filename: filenameMatch[1]!, data: Buffer.from(body) });
    }

    offset = nextBoundary;
  }

  return files;
}

/**
 * Process parsed files: validate extensions, skip existing, write to disk.
 */
export function processUploadedFiles(
  files: Array<{ filename: string; data: Buffer }>,
  wsPath: string,
  fs: typeof import("node:fs"),
): UploadResult {
  const uploaded: string[] = [];
  const skipped: Array<{ name: string; reason: string }> = [];

  for (const file of files) {
    const name = path.basename(file.filename);
    const ext = path.extname(name).toLowerCase();

    if (!ALLOWED_UPLOAD_EXT.has(ext)) {
      skipped.push({ name, reason: `Extension ${ext} not allowed` });
      continue;
    }

    const dest = path.join(wsPath, name);
    if (fs.existsSync(dest)) {
      skipped.push({ name, reason: "File already exists" });
      continue;
    }

    fs.writeFileSync(dest, file.data);
    uploaded.push(name);
  }

  return { uploaded, skipped };
}
