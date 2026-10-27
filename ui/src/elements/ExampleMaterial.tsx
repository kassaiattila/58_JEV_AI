// 231 (stage U, U0; the owner's decisions of 2026-10-27): a process's example material, where a case of it is started.
// Invented data to try the process on (`jav/app/examples.py`): the sets of things a case of it needs (the invented
// product set), each with its state, and the packets of invented documents the start form offers. Installing puts the
// sets in (the machine makes them, the person makes them active); it is the page's main step while a case cannot start
// without them. While no case keeps any of it, the material goes in one go (a second click confirms).
import { api } from "../api";
import { ConfirmButton } from "../components/ConfirmButton";
import { useAction, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";

const STATE: Record<string, [string, string]> = {
  installed: ["s-done", "Installed"], partial: ["s-warn", "Partly installed"], missing: ["s-waiting", "Not installed"],
};

export function ExampleMaterial({ pack, needed, onChanged }: { pack: string; needed: boolean; onChanged: () => void }) {
  useLocale();
  const examples = useLoad(`examples:${pack}`, () => api.processExamples(pack));
  const { busy, error, run } = useAction();
  if (examples.error) return <p className="notice error" role="alert">{examples.error.message}</p>;
  if (!examples.data) return <p className="muted">{t("Loading…")}</p>;
  const { sets, packets } = examples.data;
  if (!sets.length && !packets.length) return null;
  const installed = sets.every((s) => s.state === "installed");
  const removable = sets.length > 0 && installed && sets.every((s) => s.example);
  const changed = () => { examples.reload(); onChanged(); };
  return (
    <section className="example-material rc-stack" aria-label={t("Example material")}>
      <h3>{t("Example material")}</h3>
      <p className="muted small">{t("Invented data to try the process on: nothing in it is real, and it goes in one go while no case keeps it.")}</p>
      {sets.length ? (
        <ul className="plain">
          {sets.map((s) => {
            const [mark, label] = STATE[s.state] ?? STATE.missing;
            return (
              <li key={`${s.kind}:${s.name}`}>
                <span className={`status ${mark}`}>{t(label)}</span> {s.title}
                {s.state !== "missing" && !s.example ? <span className="muted small"> · {t("made by a person, not an example")}</span> : null}
              </li>
            );
          })}
        </ul>
      ) : null}
      {packets.length ? <p className="muted small">{t("{{n}} packets of invented documents to start a case on: the form offers them as its documents.", { n: packets.length })}</p> : null}
      {(!installed || removable) ? (
        <div className="button-row">
          {!installed ? (
            <button type="button" className={needed ? "primary" : "secondary"} disabled={busy}
              onClick={() => void run(() => api.installExamples(pack), { then: changed })}>{t("Install the example material")}</button>
          ) : null}
          {removable ? (
            <ConfirmButton className="secondary" disabled={busy}
              onConfirm={() => void run(() => api.removeExamples(pack), { then: changed })}>{t("Remove the example material")}</ConfirmButton>
          ) : null}
        </div>
      ) : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </section>
  );
}
