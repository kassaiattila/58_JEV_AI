// Appearance (057): the theme, effective at once, remembered per viewer. 157: the density switch is gone; each theme's
// swatch is a small drawing of the workspace in that theme (263: the header, the canvas, a card), from the preview tokens.
import { useState } from "react";
import { getAppearance, setAppearance, type Appearance, type Theme } from "../../appearance";
import { t, useLocale } from "../../i18n";

// the labels as Hungarian source; translation at render time (`t()`)
const THEMES: { value: Theme; label: string; halves: ("light" | "dark")[] }[] = [
  { value: "system", label: "A rendszer szerint", halves: ["light", "dark"] },
  { value: "light", label: "Light", halves: ["light"] },
  { value: "dark", label: "Dark", halves: ["dark"] },
];

export function AppearancePanel() {
  useLocale();
  const [a, setA] = useState<Appearance>(getAppearance());
  const update = (patch: Partial<Appearance>) => {
    const next = { ...a, ...patch };
    setA(next);
    setAppearance(next);
  };
  return (
    <section className="card wide" aria-label={t("Appearance")}>
      <fieldset className="dl-group">
        <legend>{t("Theme")}</legend>
        <div className="theme-choice">
          {THEMES.map((th) => (
            <label key={th.value}>
              <span className="theme-swatch" aria-hidden="true">
                {th.halves.map((h) => <span key={h} className={`swatch-${h}`}><i /><b /></span>)}
              </span>
              <span><input type="radio" name="theme" checked={a.theme === th.value} onChange={() => update({ theme: th.value })} /> {t(th.label)}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <p className="muted small">{t("The setting applies immediately and is remembered in this browser.")}</p>
    </section>
  );
}
