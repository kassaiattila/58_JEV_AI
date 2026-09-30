// 066 Á36: hibahatár. Egy nézet váratlan hibája eddig a teljes felületet üres fehér oldallá tette; most érthető üzenet és
// újratöltés-gomb jelenik meg. A mentetlen mezőjavítások a lap tárolójában megmaradnak (066 Á20), az újratöltés után
// visszajönnek.
import { Component, type ErrorInfo, type ReactNode } from "react";
import { t } from "../i18n";

export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("felületi hiba", error, info.componentStack); // i18n-ignore (fejlesztői napló)
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="page" role="alert">
        <h1>{t("Váratlan hiba a felületen")}</h1>
        <p>{t("Az oldal egy része nem jeleníthető meg. A mentetlen mezőjavításaid megmaradtak; töltsd újra az oldalt.")}</p>
        <p className="muted small mono">{this.state.error.message}</p>
        <button type="button" className="primary" onClick={() => window.location.reload()}>{t("Újratöltés")}</button>
      </main>
    );
  }
}
