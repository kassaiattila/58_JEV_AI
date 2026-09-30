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

initAppearance(); // 057: a mentett téma és sűrűség még a kirajzolás előtt
void initLanguage(); // 057: a mentett nyelv (alap: magyar); angolnál a szótár betöltése után frissít

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
);
