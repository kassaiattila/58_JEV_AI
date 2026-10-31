// 066 Á36: error boundary. Until now an unexpected error in one view turned the whole interface into a blank white
// page; now a clear message and a reload button appear. Unsaved field corrections are kept in the page's storage
// (066 Á20) and come back after the reload.
// 167 (review 160 U-12): the app also wraps each view in its own boundary (`view`), so an error in one view leaves the
// menu working; going to another address (`resetKey`) clears the error without remounting a view that works.
import { Component, type ErrorInfo, type ReactNode } from "react";
import { t } from "../i18n";

export class ErrorBoundary extends Component<{ children: ReactNode; view?: boolean; resetKey?: string }, { error: Error | null }> {
  state = { error: null as Error | null };

  componentDidUpdate(prev: { resetKey?: string }) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("felületi hiba", error, info.componentStack); // i18n-ignore (developer log)
  }

  render() {
    if (!this.state.error) return this.props.children;
    const body = (
      <>
        <h1>{t("Unexpected error in the interface")}</h1>
        <p>{t("Part of the page cannot be shown. Your unsaved field corrections have been kept; reload the page.")}</p>
        <p className="muted small mono">{this.state.error.message}</p>
        <div className="button-row">
          <button type="button" className="primary" onClick={() => window.location.reload()}>{t("Reload")}</button>
          {/* 263 (F2): the way out is the cases, the one work list */}
          {this.props.view ? <a className="button secondary" href="#/cases">{t("Cases")}</a> : null}
        </div>
      </>
    );
    // inside the app's <main> a view's boundary is a section, not a second <main>
    return this.props.view ? <section className="page" role="alert">{body}</section> : <main className="page" role="alert">{body}</main>;
  }
}
