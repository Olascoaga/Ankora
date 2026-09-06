import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./app/App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import "molstar/build/viewer/molstar.css";
import "./styles.css";
import "./design-system.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Ankora root element was not found");
}

createRoot(root).render(
  <StrictMode>
    <ErrorBoundary level="application" scope="application shell">
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
