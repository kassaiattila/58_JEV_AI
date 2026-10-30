// 263 (plan E, E1; the owner's decisions of 2026-10-30): the Settings table of contents - the groups, their sections and
// the product registry's lists - built from the sections' registry (`logic/settingsSections.ts`). The things themselves
// are in each section's list (the shared table: searchable, sortable, grouped), not in the tree; a thing's page names
// itself in the page's header (`useSettingsTitle`). A page that changes a thing says so (`settingsChanged`), and the
// counts are read again.
import { createContext, useContext, useEffect } from "react";
import { api } from "../../api";
import type { NavNode } from "../../components/Navigator";
import { useEvent, useLoad } from "../../hooks";
import { t } from "../../i18n";
import { SETTINGS_GROUPS, settingsSections } from "../../logic/settingsSections";
import { settingsHash } from "../../route";

/** A page that changed a thing of Settings tells the table of contents, which reads its counts again. */
export const SETTINGS_CHANGED = "jav:settings-changed";
export const settingsChanged = () => window.dispatchEvent(new Event(SETTINGS_CHANGED));

/** The product registry's lists, in their order, each with its address's word and its list's dataset. */
export const PRODUCT_LISTS = [
  { key: "products", label: "Products", dataset: "settings_products" }, { key: "tariffs", label: "Tariffs", dataset: "settings_tariffs" },
  { key: "rules", label: "Rules", dataset: "settings_rules" }, { key: "documents", label: "Condition documents", dataset: "settings_documents" },
  { key: "proposals", label: "Proposals", dataset: "settings_proposal_runs" },
] as const;
export type ProductList = (typeof PRODUCT_LISTS)[number]["key"];

export const groupKey = (group: string) => `g:${group}`;
export const sectionKey = (section: string) => `s:${section}`;
const listKey = (section: string, list: string) => `l:${section}/${list}`;

/** The tree's node the address stands under: the section, or the product registry's list. */
export function selectedKey(section: string, item?: string): string {
  return section === "products" && item ? listKey("products", item) : sectionKey(section);
}

/** Whether the address names one thing (its page), not a section's or a list's table. */
export const isThing = (section: string, item?: string, tab?: string) => (section === "products" ? Boolean(item && tab) : Boolean(item));

/** The partners' page's words for a new partner and for the proposals (a partner's own id is its address otherwise). */
export const PARTNER_NEW = "new";
export const PARTNER_PROPOSALS = "proposals";

export function useSettingsTree(wanted: (section: string) => boolean): NavNode[] {
  const registry = useLoad(wanted("products") ? "nav:products" : null, api.productRegistry);
  const proposals = useLoad(wanted("products") ? "nav:proposals" : null, api.ruleProposalRuns);
  useEvent(SETTINGS_CHANGED, () => {
    for (const l of [registry, proposals]) if (l.data) l.reload();
  });
  const r = registry.data;
  const counts: Record<ProductList, number | undefined> = {
    products: r?.products.length, tariffs: r?.tariffs.length, rules: r?.rules.length, documents: r?.documents.length,
    proposals: proposals.data?.runs.length,
  };
  const sections = settingsSections();
  return SETTINGS_GROUPS.map((g) => ({
    key: groupKey(g.key), label: t(g.label),
    children: sections.filter((s) => s.group === g.key).map((s) => ({
      key: sectionKey(s.key), label: t(s.navLabel ?? s.label), href: settingsHash(s.key),
      ...(s.key === "products" ? {
        children: PRODUCT_LISTS.map(({ key, label }) => ({
          key: listKey("products", key), label: t(label), href: settingsHash("products", key), count: counts[key],
        })),
      } : {}),
    })),
  }));
}

/** A thing's page names itself in the Settings page's header (its title; until it is read, the list's or the section's). */
const TitleSlot = createContext<(title: string | null) => void>(() => undefined);
export const SettingsTitleSlot = TitleSlot.Provider;
export function useSettingsTitle(title: string | null | undefined): void {
  const set = useContext(TitleSlot);
  useEffect(() => {
    set(title ?? null);
    return () => set(null);
  }, [title, set]);
}
