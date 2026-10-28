// 231 (stage U, U3d; the owner's decisions of 2026-10-28: every shared element says which processes use it): the
// processes that use a product, a tariff, a price list or an output template, each a link to its settings page. One
// request per kind (`useUsedBy`), however many rows of the list show it.
import { Fragment } from "react";
import { api, type LibraryKind, type UsedByMap } from "../api";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { routeHash } from "../route";

export function useUsedBy(kind: LibraryKind): UsedByMap | null {
  return useLoad(`used-by:${kind}`, () => api.usedBy(kind)).data?.used_by ?? null;
}

/** Nothing while the list is loading (`used` null). In a table's "Used by" column (`cell`) without its own label. */
export function UsedBy({ used, ident, cell = false }: { used: UsedByMap | null; ident: string; cell?: boolean }) {
  useLocale();
  if (!used) return null;
  const processes = used[ident] ?? [];
  if (!processes.length) return <span className="muted small used-by">{t("No process uses it")}</span>;
  return (
    <span className="small used-by">
      {cell ? null : <>{t("Used by:")}{" "}</>}
      {processes.map((p, i) => (
        <Fragment key={p.id}>
          {i ? ", " : ""}
          <a href={routeHash({ view: "settings", section: "processes", item: p.id })}>{t(p.title)}</a>
        </Fragment>
      ))}
    </span>
  );
}
