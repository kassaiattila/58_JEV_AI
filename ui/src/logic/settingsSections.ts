// 231 (plan stage C, C3e; DECISIONS 231): the sections of Settings, in their order. The shared ones are listed here; a
// domain registers its own when the interface loads (`ui/src/domains/`) - its section, or a part it adds to a shared
// section - so the Settings page and the address bar name no domain's screen. Until C3e the list was the Settings
// page's own (`views/Settings.tsx` `SETTINGS_SECTIONS`). The labels stand as source texts, translated when shown.
import type { ComponentType } from "react";

export interface SettingsSectionSpec {
  key: string;
  label: string;
  hint: string;
  /** its place in the list (the shared ones step by ten, so a domain's falls between them) */
  order: number;
  /** a domain's section's content (a shared section's is the Settings page's own) */
  Panel?: ComponentType;
}

/** A part a domain adds at the end of a shared section, under its own heading. */
export interface SettingsPart { section: string; title: string; Panel: ComponentType }

const SHARED: SettingsSectionSpec[] = [
  { key: "folders", label: "Munkamappák", hint: "Figyelt mappák: az új iratokból magától lesz munkacsomag", order: 20 },
  // 133: new labels have an English source (the Hungarian translation is in hu-native.json)
  { key: "parties", label: "Own parties", hint: "Whose money is reconciled: companies, associations and people, with their names, tax numbers and accounts", order: 30 },
  // 231 (B1): the shared partner register, the outside parties of the processes
  { key: "partners", label: "Partners", hint: "The outside parties of the processes: customers, suppliers, insured persons and brokers, each with its roles; every change is kept as a version", order: 40 },
  // 231 (B4): each process's own values over its file's: what it uses and the rule values its steps let it set
  { key: "processes", label: "Processes", hint: "Each process's own settings: the price list, template and send mode it uses and the rule values its steps let it set; a draft, its preview and making it active", order: 50 },
  { key: "recipes", label: "Feldolgozás", hint: "Hogyan dolgozza fel a rendszer az iratokat és a leveleket, mit jelentenek a beállítások, mennyibe kerülnek", order: 60 },
  // 218 (plan G-process-core P3e, DECISIONS 222): how the system decides on its own, read only
  { key: "rules", label: "Rules", hint: "How the system decides on its own: each kind of decision, the values it decides with and the version of its rules in use", order: 70 },
  // 179 (plan 170 L4, DECISIONS 178): own Excel templates of the downloads
  { key: "outputs", label: "Output templates", hint: "Your own Excel and Word templates for the downloads: upload, check, preview and make active; the markers to write in them", order: 80 },
  // 191 (plan F-quote-package B2): the seller's price lists a quote is priced from
  { key: "prices", label: "Price lists", hint: "The price lists quotes are priced from: upload, check and make active; the volume discounts, the currency and the VAT rate", order: 90 },
  { key: "users", label: "Felhasználók", hint: "A „Ki dolgozik?” választéka", order: 100 },
  { key: "appearance", label: "Megjelenés", hint: "The theme: light, dark or as the system is set", order: 110 },
  { key: "language", label: "Nyelv", hint: "A felület nyelve: magyar vagy angol", order: 120 },
  { key: "system", label: "Rendszer", hint: "A futó verzió, a feldolgozó állapota, az adattár mentése, minden futás", order: 130 },
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

/** Every section, in its order. */
export function settingsSections(): SettingsSectionSpec[] {
  return [...SHARED, ...OWN.values()].sort((a, b) => a.order - b.order);
}

/** The parts the domains add to a section, in the order they registered. */
export function settingsParts(section: string): SettingsPart[] {
  return [...PARTS.values()].filter((p) => p.section === section);
}
