// Gyors nyelvváltó a fejlécben (057): HU / EN, a Beállítások › Nyelv párja. A rövid név a saját nyelvén áll
// (`lang` attribútummal a felolvasóknak); váltás közben a gombok tiltva, sikertelen betöltésnél hibaszöveg.
import { useState } from "react";
import { setLanguage, t, useLocale, type Language } from "../i18n";

const LANGUAGES: { value: Language; code: string; name: string }[] = [
  { value: "hu", code: "HU", name: "Magyar" },
  { value: "en", code: "EN", name: "English" },
];

export function LanguageSwitch() {
  const current = useLocale();
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  async function choose(next: Language) {
    if (next === current) return;
    setBusy(true);
    setFailed(false);
    try {
      await setLanguage(next);
    } catch {
      setFailed(true);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="group" className="lang-switch" aria-label={t("A felület nyelve")} aria-busy={busy} style={{ display: "flex", alignItems: "center", gap: 4 }}>
      {LANGUAGES.map((l) => (
        <button key={l.value} type="button" className="secondary small-btn" lang={l.value} title={l.name}
          aria-pressed={current === l.value} disabled={busy} onClick={() => void choose(l.value)}>
          {l.code}
        </button>
      ))}
      {failed ? <span className="small" role="alert" style={{ color: "var(--error)" }}>{t("A nyelv betöltése nem sikerült.")}</span> : null}
    </div>
  );
}
