// 263 (plan E, E1; the owner's decision of 2026-10-30: "a table of contents and one page"): a large amount of data shown
// by its structure - groups, sections, lists and their items - as one table of contents beside one page. A branch opens
// and closes; the chosen node and the way to it are always open.
// A node is a link (its page's address), so a reload, the browser's Back and a sent link keep the choice. Until 263
// Settings had a menu, and each section a list with its detail below it.
import { Fragment, useEffect, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";
import { t, useLocale } from "../i18n";

export interface NavNode {
  key: string;
  label: string;
  /** its page; a node without one only opens and closes (a group) */
  href?: string;
  /** how many items it holds (shown muted after the label) */
  count?: number | null;
  /** a small state mark after the label (a retired thing's dash) */
  mark?: ReactNode;
  /** its branches; undefined: a leaf; `loading`: they are being read */
  children?: NavNode[];
  loading?: boolean;
}

/** The keys of the nodes on the way to `key` (itself excluded), outermost first; empty when it is not in the tree. */
export function pathTo(nodes: NavNode[], key: string | null | undefined): string[] {
  if (!key) return [];
  for (const n of nodes) {
    if (n.key === key) return [];
    if (n.children) {
      const below = pathTo(n.children, key);
      if (below.length || n.children.some((c) => c.key === key)) return [n.key, ...below];
    }
  }
  return [];
}

/** The node with `key`, anywhere in the tree. */
export function findNode(nodes: NavNode[], key: string | null | undefined): NavNode | null {
  if (!key) return null;
  for (const n of nodes) {
    if (n.key === key) return n;
    const below = n.children ? findNode(n.children, key) : null;
    if (below) return below;
  }
  return null;
}

/** 265 (code review UI-13): no caller gave the tree a search, so it has none. */
export function Navigator({ nodes, selected, open, onToggle, label }: {
  nodes: NavNode[]; selected: string | null; open: Set<string>; onToggle: (key: string) => void; label: string;
}) {
  useLocale();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => { // the chosen node comes into the tree's view when the page opens on it
    box.current?.querySelector<HTMLElement>('[aria-current="page"]')?.scrollIntoView?.({ block: "nearest" });
  }, [selected]);
  const way = new Set(pathTo(nodes, selected));
  const isOpen = (n: NavNode) => open.has(n.key) || way.has(n.key);

  const branch = (list: NavNode[], depth: number): ReactNode => (
    <ul className="nav-tree-list">
      {list.map((n) => {
        const expandable = n.children !== undefined || n.loading;
        const opened = expandable && isOpen(n);
        return (
          <Fragment key={n.key}>
            <li className={`nav-node d${Math.min(depth, 4)}`}>
              <div className="nav-row">
                {expandable ? (
                  <button type="button" className="nav-twist" aria-expanded={opened} aria-label={opened ? t("Close {{name}}", { name: n.label }) : t("Open {{name}}", { name: n.label })}
                    onClick={() => onToggle(n.key)}><Icon name="chevron" /></button>
                ) : <span className="nav-twist" aria-hidden="true" />}
                {n.href ? (
                  <a href={n.href} aria-current={n.key === selected ? "page" : undefined} title={n.label}>
                    <span className="nav-label">{n.label}</span>
                    {n.mark ? <span className="nav-mark">{n.mark}</span> : null}
                    {typeof n.count === "number" ? <span className="nav-count">{n.count}</span> : null}
                  </a>
                ) : (
                  <button type="button" className="nav-group" aria-expanded={opened} onClick={() => onToggle(n.key)}>
                    <span className="nav-label">{n.label}</span>
                  </button>
                )}
              </div>
              {opened && n.loading && !n.children?.length ? <p className="nav-loading muted small">{t("Loading…")}</p> : null}
              {opened && n.children?.length ? branch(n.children, depth + 1) : null}
            </li>
          </Fragment>
        );
      })}
    </ul>
  );

  return (
    <nav className="nav-tree" aria-label={label}>
      <div ref={box} className="nav-scroll">{branch(nodes, 0)}</div>
    </nav>
  );
}
