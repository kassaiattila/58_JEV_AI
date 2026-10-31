// Language (057, decision of 2026-09-28: HU / EN the V4 way): the language of the interface labels, remembered per
// viewer. The language names are in their own language (we do not translate them), with a `lang` attribute for screen
// readers. 264 (F5): a part of "Appearance and language" (its own page only repeated the header's switch).
import { useState } from "react";
import { setLanguage, t, useLocale, type Language } from "../../i18n";

const LANGUAGES: { value: Language; name: string }[] = [
  { value: "hu", name: "Magyar" },
  { value: "en", name: "English" },
];

export function LanguageChoice() {
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
    <>
      <fieldset className="dl-group" disabled={loading} aria-busy={loading}>
        <legend>{t("Interface language")}</legend>
        {LANGUAGES.map((l) => (
          <label key={l.value} className="check">
            <input type="radio" name="language" checked={current === l.value} onChange={() => void choose(l.value)} />
            <span lang={l.value}>{l.name}</span>
          </label>
        ))}
      </fieldset>
      {failed ? <p className="notice error" role="alert">{t("Loading the English labels failed; the interface stays in Hungarian. Please try again.")}</p> : null}
      {/* 264 (F5): that the setting is remembered is said once, below the theme and the language */}
      <p className="muted small">{t("The language only changes the interface labels; document data, names and file names stay unchanged.")}</p>
    </>
  );
}
