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

describe("1.4 lint rules", () => {
  it.each([
    ["a hex colour class", `export const c = "text-[${hash}fff]";`],
    ["an rgb() arbitrary colour", `export const c = "bg-[rgb(0,0,0)]";`],
    [
      "a hex colour in a template",
      "export const c = `border-[" + hash + "112233]`;",
    ],
    ["an oklch() value", `export const c = "oklch(0.5 0.1 20)";`],
    ["a named colour in a style", `export const s = { color: "red" };`],
    [
      "a named colour under a quoted key",
      `export const s = { "color": "red" };`,
    ],
    [
      "a named colour in an unlisted ...Color prop",
      `export const s = { borderTopColor: "red" };`,
    ],
    [
      "a colour attribute in an expression",
      `export const I = () => <svg><path fill={"red"} /></svg>;`,
    ],
    [
      "a named colour in a style attribute",
      `export const I = () => <p style={{ backgroundColor: "blue" }} />;`,
    ],
    [
      "a colour attribute",
      `export const I = () => <svg><path fill="red" /></svg>;`,
    ],
  ])("fails on %s", async (_, code) => {
    expect(await ruleIds(code, COMPONENT)).toContain("no-restricted-syntax");
  });

  it("allows token classes and currentColor", async () => {
    const code = `export const I = () => <svg className="text-destructive bg-[var(--flag-fill)]" style={{ color: "inherit", title: "red" }}><path fill="currentColor" stroke={"none"} /></svg>;`;
    expect(await ruleIds(code, COMPONENT)).toEqual([]);
  });

  it("fails on fetch in a component", async () => {
    expect(
      await ruleIds(`export const f = () => fetch("/api/x");`, COMPONENT),
    ).toContain("no-restricted-globals");
    expect(
      await ruleIds(
        `export const f = () => window.fetch("/api/x");`,
        COMPONENT,
      ),
    ).toContain("no-restricted-properties");
  });

  it("allows fetch in src/api/", async () => {
    expect(
      await ruleIds(
        `export const f = () => fetch("/api/x");`,
        "src/api/extra.ts",
      ),
    ).toEqual([]);
  });

  it("fails on dangerouslySetInnerHTML", async () => {
    const code = `export const D = ({ h }: { h: string }) => <div dangerouslySetInnerHTML={{ __html: h }} />;`;
    expect(await ruleIds(code, COMPONENT)).toContain("no-restricted-syntax");
  });
});
