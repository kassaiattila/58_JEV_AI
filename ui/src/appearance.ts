// Megjelenés (057): téma (világos / sötét / a rendszer szerint) és sűrűség (tágas / tömör). Nézőnként, a böngészőben
// tárolva (a régi V4 is így kezelte); tárolás híján (privát ablak) az alapérték él.
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
    /* privát ablakban nincs tárolás: a beállítás csak a munkamenetig él */
  }
  applyAppearance(a);
}

/** Induláskor: alkalmazza a mentett beállítást, és „rendszer” témánál követi a rendszer váltását. */
export function initAppearance(): void {
  applyAppearance();
  if (typeof window.matchMedia === "function") {
    window.matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", () => applyAppearance());
  }
}
