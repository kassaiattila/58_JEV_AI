// Language (057, decision of 2026-09-28: HU / EN the V4 way): the language of the interface labels, remembered per
// viewer. The language names are in their own language (we do not translate them), with a `lang` attribute for screen
// readers.
import { useState } from "react";
import { setLanguage, t, useLocale, type Language } from "../../i18n";

const LANGUAGES: { value: Language; name: string }[] = [
  { value: "hu", name: "Magyar" },
  { value: "en", name: "English" },
];

export function LanguagePanel() {
  const current = useLocale();
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  async function choose(next: Language) {
    setLoading(true);
    setFailed(false);
    try {
      await setLanguage(next);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="card wide" aria-label={t("Nyelv")}>
      <fieldset className="dl-group" disabled={loading} aria-busy={loading}>
        <legend>{t("A felület nyelve")}</legend>
        {LANGUAGES.map((l) => (
          <label key={l.value} className="check">
            <input type="radio" name="language" checked={current === l.value} onChange={() => void choose(l.value)} />
            <span lang={l.value}>{l.name}</span>
          </label>
        ))}
      </fieldset>
      {failed ? <p className="notice error" role="alert">{t("Az angol feliratok betöltése nem sikerült; a felület magyar marad. Próbáld újra.")}</p> : null}
      <p className="muted small">{t("A nyelv csak a felület feliratait váltja; az iratok adatai, a nevek és a fájlnevek változatlanok. A beállítás ebben a böngészőben megmarad.")}</p>
    </section>
  );
}
