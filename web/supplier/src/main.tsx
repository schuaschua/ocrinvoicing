import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/App";
import { readUploadToken, reloadOnNewLink } from "@/link";
import "@/index.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("index.html has no #root element");
}
// Read once, at start-up (AD-6); a new link in the same tab reloads the page.
const token = readUploadToken(window.location.hash);
reloadOnNewLink(window);
createRoot(root).render(
  <StrictMode>
    <App token={token} />
  </StrictMode>,
);
