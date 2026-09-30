// Appearance (057): theme and density, effective at once, remembered per viewer.
import { useState } from "react";
import { getAppearance, setAppearance, type Appearance, type Density, type Theme } from "../../appearance";
import { t, useLocale } from "../../i18n";

// the labels as Hungarian source; translation at render time (`t()`)
const THEMES: { value: Theme; label: string; swatch: string }[] = [
  { value: "system", label: "A rendszer szerint", swatch: "linear-gradient(90deg, #f4f4f5 50%, #16161b 50%)" },
  { value: "light", label: "Világos", swatch: "#f4f4f5" },
  { value: "dark", label: "Sötét", swatch: "#16161b" },
];
const DENSITIES: { value: Density; label: string; hint: string }[] = [
  { value: "comfortable", label: "Tágas", hint: "több levegő, nagyobb sorok" },
  { value: "compact", label: "Tömör", hint: "több sor fér egy képernyőre" },
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
    <section className="card wide" aria-label={t("Megjelenés")}>
      <fieldset className="dl-group">
        <legend>{t("Téma")}</legend>
        <div className="theme-choice">
          {THEMES.map((th) => (
            <label key={th.value}>
              <span className="theme-swatch" style={{ background: th.swatch }} aria-hidden="true" />
              <span><input type="radio" name="theme" checked={a.theme === th.value} onChange={() => update({ theme: th.value })} /> {t(th.label)}</span>
            </label>
          ))}
        </div>
      </fieldset>
      <fieldset className="dl-group">
        <legend>{t("Sűrűség")}</legend>
        {DENSITIES.map((d) => (
          <label key={d.value} className="check">
            <input type="radio" name="density" checked={a.density === d.value} onChange={() => update({ density: d.value })} />
            <span><strong>{t(d.label)}</strong> <span className="muted small">{t(d.hint)}</span></span>
          </label>
        ))}
      </fieldset>
      <p className="muted small">{t("A beállítás azonnal érvényes, és ebben a böngészőben megmarad.")}</p>
    </section>
  );
}
