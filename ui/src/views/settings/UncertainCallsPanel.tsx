// 076: paid calls with an uncertain outcome on the System page. When the program stopped in the middle of a paid
// call, it does not know whether the provider charged for it; the call keeps its maximum cost reserved from the run's
// budget and the step is not repeated automatically. Here a person settles it after checking the provider's console:
// with the actual cost (or none, if unknown) and a note. The same as `python -m jav.cli calls-resolve`.
import { useState } from "react";
import { api, type ApiError, type UncertainCall } from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";

/** A cost typed by a person: empty = unknown (the maximum stays committed); otherwise a non-negative dollar amount. */
export function parseCost(text: string): { ok: boolean; value: string | null } {
  const s = text.trim().replace(",", ".");
  if (!s) return { ok: true, value: null };
  return /^\d{1,3}(\.\d{1,6})?$/.test(s) ? { ok: true, value: s } : { ok: false, value: null };
}

function CallRow({ call, onDone }: { call: UncertainCall; onDone: () => void }) {
  const [cost, setCost] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const parsed = parseCost(cost);
  const ready = parsed.ok && note.trim().length >= 3;

  async function resolve() {
    setError(null);
    try {
      await api.resolveUncertainCall(call.id, { cost_usd: parsed.value, note: note.trim() });
      onDone();
    } catch (e) {
      setError((e as ApiError).message);
    }
  }

  return (
    <li className="uncertain-call">
      <p className="small">
        <span className="mono">#{call.id}</span>{" "}
        {t("{{provider}}, {{step}} lépés, futás: {{run}}, {{when}}; lefoglalva legfeljebb {{max}} USD", {
          provider: call.provider, step: call.step_id, run: call.run_id, when: when(call.created_at), max: call.max_cost_usd,
        })}
      </p>
      <div className="row">
        <label>
          {t("Tényleges költség (USD, üresen: ismeretlen)")}
          <input value={cost} onChange={(e) => setCost(e.target.value)} inputMode="decimal" aria-invalid={!parsed.ok} />
        </label>
        <label>
          {t("Megjegyzés (például mit mutatott a szolgáltató felülete)")}
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} />
        </label>
        <ConfirmButton onConfirm={() => void resolve()} disabled={!ready} ariaLabel={t("Lezárás")}>
          {t("Lezárás")}
        </ConfirmButton>
      </div>
      {!parsed.ok ? <p className="notice error">{t("A költség nem szám (például 0.012).")}</p> : null}
      {error ? <p className="notice error">{error}</p> : null}
    </li>
  );
}

export function UncertainCallsPanel() {
  useLocale();
  const d = useLoad("uncertain-calls", api.uncertainCalls, 60000);
  const calls = d.data?.calls ?? [];
  return (
    <section className="card wide" aria-label={t("Bizonytalan kimenetű hívások")}>
      <div className="card-head">
        <h3>{t("Bizonytalan kimenetű hívások")}</h3>
      </div>
      {d.error ? <p className="notice error">{d.error.message}</p> : null}
      {/* 085 (re-audit U01): "none" only for a list actually loaded, not while loading or after a failed request */}
      {d.data ? (
        <p role="status" className={calls.length ? "notice" : ""}>
          {calls.length
            ? t("{{n}} fizetős hívásnál nem tudni, lefutott-e; amíg nincs lezárva, a futás kerete a legnagyobb költséggel számol vele, és a lépés nem ismétlődik.", { n: calls.length })
            : t("Nincs lezáratlan, bizonytalan kimenetű hívás.")}
        </p>
      ) : !d.error ? <p className="muted">{t("Betöltés…")}</p> : null}
      {calls.length ? <ul className="plain">{calls.map((c) => <CallRow key={c.id} call={c} onDone={d.reload} />)}</ul> : null}
    </section>
  );
}
