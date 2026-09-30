// Felületi nyelv (057, döntés 2026-09-28: HU / EN a régi V4 módján). Portolva a régi `ui/src/i18n/index.ts`-ből
// (csak olvasva): könyvtár nélkül, a kulcs maga a magyar felirat, az angol szótár (`en-*.json`) csak angolra váltáskor
// töltődik be. Szabályok (a régi README szerint):
// - `t()`-be csak a felület saját szövege kerül; kinyert érték, levéltartalom, fájlnév, felhasználói szöveg SOHA;
// - a komponens `useLocale()`-lal iratkozik fel, így a nyelvváltás helyben frissít, a munkapéldány (mentetlen
//   javítás, kijelölés) megmarad; a nyelv soha nem React `key`;
// - modul betöltésekor nem fordítunk (a fordítás a kirajzoláskor történik);
// - hiányzó fordításnál a magyar felirat látszik; a `npm run i18n:check` a hiányt build előtt jelzi.
import { useSyncExternalStore } from "react";

export type Language = "hu" | "en";
export type Messages = Record<string, string>;
export const LANGUAGE_STORAGE_KEY = "jav.ui-language";

let language: Language = "hu";
let english: Messages = {};
let englishLoad: Promise<void> | undefined;
let request = 0;
const listeners = new Set<() => void>();
const subscribe = (fn: () => void) => { listeners.add(fn); return () => { listeners.delete(fn); }; };

export const getLanguage = (): Language => language;
export const getLocale = (): "hu-HU" | "en-GB" => (language === "en" ? "en-GB" : "hu-HU");

/** A nyelvváltás helyben frissíti a feliratokat (a munkapéldány és a kijelölés megmarad). */
export function useLocale(): Language {
  return useSyncExternalStore(subscribe, getLanguage, getLanguage);
}

/** A felület saját szövege a választott nyelven; `{{név}}` helyére a paraméter kerül. */
export function t(source: string, params?: Record<string, unknown>): string {
  const translated = language === "en" ? (english[source] ?? source) : source;
  return params
    ? translated.replace(/\{\{(\w+)\}\}/g, (token, key: string) => (Object.prototype.hasOwnProperty.call(params, key) ? String(params[key] ?? "") : token))
    : translated;
}

export async function setLanguage(next: Language): Promise<void> {
  if (next !== "hu" && next !== "en") return;
  const mine = ++request; // az utolsó kérés nyer
  if (next === "en") {
    englishLoad ??= import("./en").then((m) => { english = m.default; }).catch((e) => { englishLoad = undefined; throw e; });
    await englishLoad;
  }
  if (mine !== request) return;
  language = next;
  if (typeof document !== "undefined") document.documentElement.lang = next;
  try {
    localStorage.setItem(LANGUAGE_STORAGE_KEY, next);
  } catch {
    /* privát ablakban nincs tárolás: a nyelv csak a munkamenetig él */
  }
  listeners.forEach((fn) => fn());
}

/** Induláskor: a mentett nyelv (alap: magyar). */
export async function initLanguage(): Promise<void> {
  let saved: string | null = null;
  try {
    saved = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  } catch {
    /* nincs tárolás */
  }
  await setLanguage(saved === "en" ? "en" : "hu");
}
