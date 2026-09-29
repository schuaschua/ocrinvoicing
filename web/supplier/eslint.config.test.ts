// @vitest-environment node
import { ESLint } from "eslint";
import { describe, expect, it } from "vitest";

const eslint = new ESLint({ cwd: import.meta.dirname });

async function ruleIds(code: string, filePath: string): Promise<string[]> {
  const [result] = await eslint.lintText(code, { filePath });
  return (result?.messages ?? []).map((m) => m.ruleId ?? m.message);
}

// Built at run time so this file itself passes the colour rule.
const hash = "#";
const COMPONENT = "src/components/Example.tsx";

// The first case starts ESLint and its TypeScript parser from cold, which can take
// more than the default 5 s while the whole suite runs in CI.
describe("1.4 lint rules", { timeout: 30_000 }, () => {
  it("fails on hard-coded colours and allows token classes", async () => {
    for (const code of [
      `export const c = "text-[${hash}fff]";`,
      `export const I = () => <p style={{ backgroundColor: "blue" }} />;`,
    ]) {
      expect(await ruleIds(code, COMPONENT)).toContain("no-restricted-syntax");
    }
    const tokens = `export const I = () => <svg className="text-destructive bg-[var(--flag-fill)]"><path fill="currentColor" /></svg>;`;
    expect(await ruleIds(tokens, COMPONENT)).toEqual([]);
  });

  it("fails on dangerouslySetInnerHTML, and on fetch outside src/api/", async () => {
    const html = `export const D = ({ h }: { h: string }) => <div dangerouslySetInnerHTML={{ __html: h }} />;`;
    expect(await ruleIds(html, COMPONENT)).toContain("no-restricted-syntax");
    const fetchCall = `export const f = () => fetch("/api/x");`;
    expect(await ruleIds(fetchCall, COMPONENT)).toContain(
      "no-restricted-globals",
    );
    expect(await ruleIds(fetchCall, "src/api/extra.ts")).toEqual([]);
  });
});
