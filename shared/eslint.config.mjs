// shared/quality/ (Story 1.9) is linted with the supplier page's rules, which import
// it: ci/checks.sh runs the supplier app's ESLint on it, and ESLint finds this file.
export { default } from "../web/supplier/eslint.config.js";
