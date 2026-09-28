import { defineConfig, devices } from "@playwright/test";

// The automated accessibility check (UX-DR21, Story 1.4): Chromium against the built
// app served by `vite preview`. Build first (`npm run build`); ci/checks.sh does.
const PORT = 4174;
const junit = process.env.PLAYWRIGHT_JUNIT_OUTPUT_FILE;

export default defineConfig({
  testDir: "e2e",
  forbidOnly: Boolean(process.env.TF_BUILD),
  retries: 0,
  reporter: junit ? [["list"], ["junit"]] : "list",
  use: { baseURL: `http://127.0.0.1:${PORT}` },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `npm exec --no -- vite preview --host 127.0.0.1 --port ${PORT} --strictPort`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: false,
  },
});
