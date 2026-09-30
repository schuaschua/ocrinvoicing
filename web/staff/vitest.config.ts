import { defineConfig, mergeConfig } from "vitest/config";
import viteConfig from "./vite.config.ts";

// ci/checks.sh passes the coverage floor (60%) on the command line, so this file
// cannot lower it.
export default mergeConfig(
  viteConfig,
  defineConfig({
    test: {
      environment: "jsdom",
      // shared/quality/'s tests run once, in web/supplier: the staff app's goods-in
      // scan (Story 4.1) uses the same module and the same copied device check.
      include: ["src/**/*.test.{ts,tsx}", "*.test.ts"],
      setupFiles: ["./src/test/setup.ts"],
      coverage: {
        provider: "v8",
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/**/*.test.{ts,tsx}", "src/test/**"],
      },
    },
  }),
);
