// 231 (plan stage C, C3e; DECISIONS 231): the sections of Settings, in their order. The shared ones are listed here; a
// domain registers its own when the interface loads (`ui/src/domains/`) - its section, or a part it adds to a shared
// section - so the Settings page and the address bar name no domain's screen. Until C3e the list was the Settings
// page's own (`views/Settings.tsx` `SETTINGS_SECTIONS`). The labels stand as source texts, translated when shown.
// 231 (U3e; the owner's decisions of 2026-10-28): the sections stand in three groups - the processes, the shared
// library every process chooses from, and the system - and the menu shows each group under its name.
import type { ComponentType } from "react";

export type SettingsGroup = "processes" | "library" | "system";

/** The groups of the menu, in their order, each with its name as a source text. */
export const SETTINGS_GROUPS: { key: SettingsGroup; label: string }[] = [
  { key: "processes", label: "Processes" }, { key: "library", label: "Shared library" }, { key: "system", label: "System" },
];

export interface SettingsSectionSpec {
  key: string;
  label: string;
  /** its name in the menu, when it differs from the page's title (the processes' overview) */
  navLabel?: string;
  hint: string;
  /** the menu group it stands in */
  group: SettingsGroup;
  /** its place in its group (the shared ones step by ten, so a domain's falls between them) */
  order: number;
  /** a domain's section's content (a shared section's is the Settings page's own) */
  Panel?: ComponentType;
}

/** A part a domain adds at the end of a shared section, under its own heading. */
export interface SettingsPart { section: string; title: string; Panel: ComponentType }

const SHARED: SettingsSectionSpec[] = [
  // 231 (B4): each process's own values over its file's: what it uses and the rule values its steps let it set
  { key: "processes", label: "Processes", navLabel: "All processes", hint: "Each process's own settings: the price list, template and send mode it uses and the rule values its steps let it set; a draft, its preview and making it active", group: "processes", order: 100 },
  // 231 (B1): the shared partner register, the outside parties of the processes (U3e: the own parties among them)
  { key: "partners", label: "Partners", hint: "The parties of the processes: customers, suppliers, insured persons and brokers, each with its roles, and the own parties; every change is kept as a version", group: "library", order: 200 },
  // 231 (stage D, D-c6): the product registry: what an offer is built from and what its premium is computed from
  // 231 (U3c; the owner's decision of 2026-10-28): a product brings its tariff, so the tariffs are a list of the products' page
  { key: "products", label: "Products", hint: "What an offer is built from: the products with their cover modules and tariffs, the condition documents and the rules read from them, each kept as versions; a draft's checks and making it active", group: "library", order: 220 },
  // 179 (plan 170 L4, DECISIONS 178): own Excel templates of the downloads
  { key: "outputs", label: "Output templates", hint: "Your own Excel and Word templates for the downloads: upload, check, preview and make active; the markers to write in them", group: "library", order: 240 },
  // 231 (U3f; the owner's decision of 2026-10-28): the letter frames, edited as versions
  { key: "letters", label: "Letter frames", hint: "The texts of the letters that go with a printed document: a changed text is a draft until it is made active, and a case keeps the text it started with", group: "library", order: 250 },
  { key: "users", label: "Felhasználók", hint: "A „Ki dolgozik?” választéka", group: "system", order: 300 },
  { key: "appearance", label: "Megjelenés", hint: "The theme: light, dark or as the system is set", group: "system", order: 310 },
  { key: "language", label: "Nyelv", hint: "A felület nyelve: magyar vagy angol", group: "system", order: 320 },
  { key: "folders", label: "Munkamappák", hint: "Figyelt mappák: az új iratokból magától lesz iratköteg", group: "system", order: 330 },
  { key: "recipes", label: "Feldolgozás", hint: "Hogyan dolgozza fel a rendszer az iratokat és a leveleket, mit jelentenek a beállítások, mennyibe kerülnek", group: "system", order: 350 },
  // 218 (plan G-process-core P3e, DECISIONS 222): how the system decides on its own
  // 231 (U4d; the owner's decisions of 2026-10-29): the rule values' defaults are set here (until then read only, "Rules")
  { key: "rules", label: "Defaults", hint: "How the system decides on its own: each kind of decision and the values it decides with, which the installation may set as its defaults", group: "system", order: 360 },
  // U3e: the running system itself (until then "System", now the name of its group)
  { key: "system", label: "Operations", hint: "A futó verzió, a feldolgozó állapota, az adattár mentése, minden futás", group: "system", order: 370 },
];
const OWN = new Map<string, SettingsSectionSpec>();
const PARTS = new Map<string, SettingsPart>();

/** Registers a domain's section (a second registration of the same key replaces the first). */
export function registerSettingsSection(spec: SettingsSectionSpec & { Panel: ComponentType }): void {
  OWN.set(spec.key, spec);
}

/** Registers a part a domain adds to a shared section, by the part's title. */
export function registerSettingsPart(part: SettingsPart): void {
  PARTS.set(`${part.section}/${part.title}`, part);
}

/** Every section, in its order (the groups' order first). */
export function settingsSections(): SettingsSectionSpec[] {
  const place = (g: SettingsGroup) => SETTINGS_GROUPS.findIndex((x) => x.key === g);
  return [...SHARED, ...OWN.values()].sort((a, b) => place(a.group) - place(b.group) || a.order - b.order);
}

/** The parts the domains add to a section, in the order they registered. */
export function settingsParts(section: string): SettingsPart[] {
  return [...PARTS.values()].filter((p) => p.section === section);
}
