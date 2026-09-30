// Interface language (057, decision of 2026-09-28: HU / EN the way the legacy V4 does it). Ported from the legacy
// `ui/src/i18n/index.ts` (only read): without a library, the key is the Hungarian label itself, and the English
// dictionary (`en-*.json`) is loaded only when switching to English. Rules (from the legacy README):
// - only the interface's own text goes into `t()`; an extracted value, email content, file name or user text NEVER;
// - a component subscribes with `useLocale()`, so a language switch updates in place and the working copy (unsaved
//   correction, selection) is kept; the language is never a React `key`;
// - nothing is translated when a module loads (translation happens at render time);
// - for a missing translation the Hungarian label shows; `npm run i18n:check` reports the gap before the build.
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

/** A language switch updates the labels in place (the working copy and the selection are kept). */
export function useLocale(): Language {
  return useSyncExternalStore(subscribe, getLanguage, getLanguage);
}

/** The interface's own text in the chosen language; each `{{name}}` is replaced by the parameter. */
export function t(source: string, params?: Record<string, unknown>): string {
  const translated = language === "en" ? (english[source] ?? source) : source;
  return params
    ? translated.replace(/\{\{(\w+)\}\}/g, (token, key: string) => (Object.prototype.hasOwnProperty.call(params, key) ? String(params[key] ?? "") : token))
    : translated;
}

export async function setLanguage(next: Language): Promise<void> {
  if (next !== "hu" && next !== "en") return;
  const mine = ++request; // the last request wins
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
    /* no storage in a private window: the language lasts only for the session */
  }
  listeners.forEach((fn) => fn());
}

/** At start-up: the saved language (default: Hungarian). */
export async function initLanguage(): Promise<void> {
  let saved: string | null = null;
  try {
    saved = localStorage.getItem(LANGUAGE_STORAGE_KEY);
  } catch {
    /* no storage */
  }
  await setLanguage(saved === "en" ? "en" : "hu");
}
