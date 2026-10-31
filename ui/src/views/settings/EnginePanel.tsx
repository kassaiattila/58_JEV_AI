// 160-D (plan F-csak-gpt Sz4; the owner's decision of 2026-10-16): the application's AI engine, JEV and GPT (the default)
// or GPT only. It is the default of every new processing setting that does not name one; saved package settings and
// started runs keep their own, so the panel says so before anyone changes it. A choice is a selection (ink border on
// the neutral tint), and its save is solid only while there is something to save (docs/guides/DESIGN.md).
import { useEffect, useState } from "react";
import { api, ApiError, type Engine } from "../../api";
import { FormActions } from "../../components/FormActions";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { ENGINE, when } from "../../labels";

const CHOICES: { value: Engine; title: string; text: string }[] = [
  { value: "jev", title: "JEV and GPT (recommended)",
    text: "JEV recognises each document's type and each email's intent, and chooses or checks the extracted values; GPT extracts where a type's path needs it. This is the way the golden sets measure." },
  { value: "gpt", title: "GPT only, without JEV",
    text: "GPT recognises the type and the intent and extracts the data; the code checks each value against the document. No JEV cost, but more OpenAI cost per document; a value whose GPT confidence cannot be measured becomes a to-do." },
];

export function EnginePanel() {
  useLocale();
  const setting = useLoad("engine", api.engine);
  const [choice, setChoice] = useState<Engine | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  useEffect(() => { if (setting.data) setChoice(setting.data.engine); }, [setting.data]);
  const saved = setting.data?.engine ?? null;
  const dirty = choice !== null && saved !== null && choice !== saved;

  async function save() {
    if (!choice) return;
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.saveEngine(choice);
      setMsg({ error: false, text: t("Saved. New processing settings use: {{engine}}.", { engine: ENGINE[res.engine] }) });
      setting.reload();
    } catch (e) {
      setMsg({ error: true, text: e instanceof ApiError ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card wide" aria-label={t("AI engine")}>
      <div className="card-head">
        <h3>{t("AI engine")}</h3>
        {setting.data ? (
          <span className="muted small">{setting.data.actor
            ? t("Set by {{actor}}, {{when}}", { actor: setting.data.actor, when: when(setting.data.updated_at) })
            : t("The default; nobody has changed it")}</span>
        ) : null}
      </div>
      <p className="small">{t("Which AI the processing asks. The choice applies to every new processing setting: a new package, a package whose settings were never saved, a mailbox download, a watched folder and a workflow step without its own choice. Saved package settings and started runs keep their own engine.")}</p>
      {setting.error ? <p className="notice error" role="alert">{setting.error.message}</p> : null}
      {setting.data && choice ? (
        <>
          <fieldset className="wizard-choices engine-choices">
            <legend className="sr-only">{t("AI engine")}</legend>
            {CHOICES.map((c) => (
              <label key={c.value} className="wizard-choice">
                <input type="radio" name="app-engine" checked={choice === c.value} onChange={() => { setChoice(c.value); setMsg(null); }} />
                <span><strong>{t(c.title)}</strong><span className="muted small">{t(c.text)}</span></span>
              </label>
            ))}
          </fieldset>
          <FormActions busy={busy} note={dirty ? t("Packages with saved settings keep their engine; change those in the package's Processing section.") : null}>
            <button type="button" className={dirty ? "primary" : "secondary"} disabled={!dirty || busy} onClick={() => void save()}>
              {busy ? t("Saving…") : t("Save")}
            </button>
          </FormActions>
        </>
      ) : !setting.error ? <p className="muted">{t("Loading…")}</p> : null}
      {msg ? <p className={msg.error ? "notice error" : "muted small"} role={msg.error ? "alert" : "status"}>{msg.text}</p> : null}
    </section>
  );
}
