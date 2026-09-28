// coding-style.md section 1 (ESLint recommended + typescript-eslint recommended +
// react-hooks) plus the project rules the tools can enforce: no hard-coded colours
// (rule 17), no fetch outside src/api/ (rule 15) and no dangerouslySetInnerHTML
// (security.md rule 22). eslint.config.test.ts proves each rule fires.
import js from "@eslint/js";
import { defineConfig, globalIgnores } from "eslint/config";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

// A hex colour or a CSS colour function, in any string: a class name (including a
// Tailwind arbitrary value such as bg-[#fff]), an inline style or an SVG attribute.
const COLOUR =
  "/(#[0-9a-fA-F]{3,8}\\b|\\b(rgba?|hsla?|hwb|lab|lch|oklab|oklch|color-mix)\\()/";
const COLOUR_MESSAGE =
  "Hard-coded colour: use a design token from DESIGN.md (a CSS variable or its Tailwind class), coding-style.md rule 17.";
// Style properties and SVG/JSX attributes that take a colour: background, fill,
// stroke, and anything named ...Color/...color (color, borderTopColor, stopColor).
const COLOUR_NAME = "/^(background|fill|stroke|[a-zA-Z]*[cC]olor)$/";
const COLOUR_KEYWORDS = "/^(none|inherit|currentColor|transparent)$/";
const FETCH_MESSAGE =
  "Call the API only through src/api/ (coding-style.md rule 15, UX-DR3).";

const COLOUR_RULES = [
  { selector: `Literal[value=${COLOUR}]`, message: COLOUR_MESSAGE },
  { selector: `TemplateElement[value.raw=${COLOUR}]`, message: COLOUR_MESSAGE },
  // { color: "red" } and { "borderTopColor": "red" }
  {
    selector: `Property[key.name=${COLOUR_NAME}] > Literal.value:not([value=${COLOUR_KEYWORDS}])`,
    message: COLOUR_MESSAGE,
  },
  {
    selector: `Property[key.value=${COLOUR_NAME}] > Literal.value:not([value=${COLOUR_KEYWORDS}])`,
    message: COLOUR_MESSAGE,
  },
  // fill="red" and fill={"red"}
  {
    selector: `JSXAttribute[name.name=${COLOUR_NAME}] > Literal:not([value=${COLOUR_KEYWORDS}])`,
    message: COLOUR_MESSAGE,
  },
  {
    selector: `JSXAttribute[name.name=${COLOUR_NAME}] > JSXExpressionContainer > Literal:not([value=${COLOUR_KEYWORDS}])`,
    message: COLOUR_MESSAGE,
  },
];
const HTML_RULES = [
  {
    selector: "JSXAttribute[name.name='dangerouslySetInnerHTML']",
    message: "Never use dangerouslySetInnerHTML (security.md rule 22).",
  },
  {
    selector: "Property[key.name='dangerouslySetInnerHTML']",
    message: "Never use dangerouslySetInnerHTML (security.md rule 22).",
  },
];

export default defineConfig([
  globalIgnores(["dist", "coverage", "playwright-report", "test-results"]),
  {
    files: ["**/*.{ts,tsx,js}"],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2023,
      globals: { ...globals.browser },
    },
    rules: {
      "no-restricted-syntax": ["error", ...COLOUR_RULES, ...HTML_RULES],
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: FETCH_MESSAGE },
        { name: "XMLHttpRequest", message: FETCH_MESSAGE },
      ],
      "no-restricted-properties": [
        "error",
        { object: "window", property: "fetch", message: FETCH_MESSAGE },
        { object: "globalThis", property: "fetch", message: FETCH_MESSAGE },
        { object: "self", property: "fetch", message: FETCH_MESSAGE },
      ],
    },
  },
  {
    // The one API client (UX-DR3).
    files: ["src/api/**/*.ts"],
    rules: {
      "no-restricted-globals": "off",
      "no-restricted-properties": "off",
    },
  },
  {
    // Tests compare against the DESIGN.md values, so they may spell colours out.
    files: ["**/*.test.{ts,tsx}"],
    rules: { "no-restricted-syntax": ["error", ...HTML_RULES] },
  },
  {
    // Build, test and e2e tooling runs in Node.
    files: ["*.config.{ts,js}", "*.test.ts", "e2e/**/*.ts"],
    languageOptions: { globals: { ...globals.node } },
  },
]);
