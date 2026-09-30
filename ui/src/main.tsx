import "@fontsource/geist-sans/400.css";
import "@fontsource/geist-sans/600.css";
import "@fontsource/geist-mono/400.css";
import "./styles.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { initAppearance } from "./appearance";
import { initLanguage } from "./i18n";

initAppearance(); // 057: the saved theme and density, already before rendering
void initLanguage(); // 057: the saved language (default: Hungarian); for English it updates after the dictionary loads

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
