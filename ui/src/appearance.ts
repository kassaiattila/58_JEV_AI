// Appearance (057): theme (light / dark / following the system) and density (comfortable / compact). Per viewer,
// stored in the browser (the legacy V4 handled it the same way); without storage (private window) the default applies.
export type Theme = "light" | "dark" | "system";
export type Density = "comfortable" | "compact";
export interface Appearance { theme: Theme; density: Density }

const KEY = "jav.appearance";
const DEFAULT: Appearance = { theme: "system", density: "comfortable" };

export function getAppearance(): Appearance {
  try {
    return { ...DEFAULT, ...(JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Appearance>) };
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
  root.dataset.density = a.density;
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
