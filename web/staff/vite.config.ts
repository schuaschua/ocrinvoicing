import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const src = fileURLToPath(new URL("./src", import.meta.url));
// shared/quality/ (client photo check) and shared/quality-thresholds.json (Story 1.9).
const shared = fileURLToPath(new URL("../../shared", import.meta.url));

// security.md rule 25 headers from their one source, which the Function apps read
// too (backend/src/invoicing/adapters/http.py). The preview server sends them, so the
// a11y check fails on anything the deployed app would block, such as an inline script.
export const SECURITY_HEADERS: Record<string, string> = JSON.parse(
  readFileSync(`${shared}/security-headers.json`, "utf8"),
);

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": src, "@shared": shared },
  },
  build: {
    // No data: URIs: the CSP allows 'self' only.
    assetsInlineLimit: 0,
  },
  server: {
    fs: { allow: [fileURLToPath(new URL(".", import.meta.url)), shared] },
  },
  preview: { headers: SECURITY_HEADERS },
});
