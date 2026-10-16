// Appearance (057): the theme (light / dark / following the system). Per viewer, stored in the browser (the legacy V4
// handled it the same way); without storage (private window) the default applies. 157: the density switch is gone
// (one density for everyone, as the design brief decided); a density remembered from before is ignored.
export type Theme = "light" | "dark" | "system";
export interface Appearance { theme: Theme }

const KEY = "jav.appearance";
const DEFAULT: Appearance = { theme: "system" };

export function getAppearance(): Appearance {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Appearance>;
    return { theme: saved.theme ?? DEFAULT.theme };
  } catch {
    return DEFAULT;
  }
}

function effectiveTheme(t: Theme): "light" | "dark" {
  if (t !== "system") return t;
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function applyAppearance(a: Appearance = getAppearance()): void {
  const root = document.documentElement;
  root.dataset.theme = effectiveTheme(a.theme);
}

export function setAppearance(a: Appearance): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(a));
  } catch {
    /* no storage in a private window: the setting lasts only for the session */
  }
  applyAppearance(a);
}

/** At start-up: applies the saved setting and, with the „rendszer” (system) theme, follows the system when it
 *  switches. */
export function initAppearance(): void {
  applyAppearance();
  if (typeof window.matchMedia === "function") {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyAppearance());
  }
}
