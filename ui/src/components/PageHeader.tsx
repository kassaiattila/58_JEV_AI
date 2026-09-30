// Unified page header (057): breadcrumbs, title, one-line summary, the main action top right — the same on every page.
import type { ReactNode } from "react";
import { t, useLocale } from "../i18n";

export interface Crumb { label: string; href?: string }

export function PageHeader({ crumbs, title, badge, summary, actions }: {
  crumbs?: Crumb[]; title: ReactNode; badge?: ReactNode; summary?: ReactNode; actions?: ReactNode;
}) {
  useLocale();
  return (
    <header className="page-head">
      <div className="page-head-main">
        {crumbs?.length ? (
          <nav aria-label={t("Hely")} className="crumb">
            {crumbs.map((c, i) => (
              <span key={`${c.label}-${i}`}>{c.href ? <a href={c.href}>{c.label}</a> : c.label}{i < crumbs.length - 1 ? " / " : ""}</span>
            ))}
          </nav>
        ) : null}
        <h1>{title}{badge}</h1>
        {summary ? <p className="muted page-summary">{summary}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}
