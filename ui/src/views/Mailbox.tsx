// Postafiók (048 T2): mit olvassunk (postafiók, mappa, időszak) → ingyenes darabszám-előnézet → letöltés most, vagy
// ütemezés. Minden letöltést a feldolgozó futtat; az eredmény a letöltési naplóban látszik, az új levelekből
// munkacsomag lesz a levél-szándék recepttel. Fizetős feldolgozás nem indul magától (2026-09-28 döntés).
import { useState } from "react";
import { api, ApiError, getActor, NO_ACTOR, type MailboxCount, type MailboxPull, type MailboxRequest } from "../api";
import { DataTable } from "../components/DataTable";
import { Picker } from "../components/Picker";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { intervals, intervalText, when } from "../labels";

export function pullSummary(p: Pick<MailboxPull, "status" | "result">): string {
  const r = p.result;
  if (p.status === "error") return r?.error ?? t("Hiba");
  if (!r) return "–";
  const parts = [t("{{n}} új levél", { n: (r.new ?? 0) + (r.changed ?? 0) })];
  if (r.changed) parts[0] += ` ${t("({{n}} megváltozott)", { n: r.changed })}`;
  if (r.duplicate) parts.push(t("{{n}} már megvolt", { n: r.duplicate }));
  return parts.join(" · ");
}

/** A régi szkript gyakori hibái a felület nyelvén; ismeretlennél az eredeti szöveg. */
export function bridgeErrorText(message: string): string {
  if (/must match exactly one Outlook account/.test(message)) {
    return t("Ez a cím egyetlen Outlook-fiókkal sem egyezik ezen a gépen. Ellenőrizd a címet (pontosan úgy, ahogy az Outlookban szerepel).");
  }
  if (/Outlook must already be running/.test(message)) return t("Az Outlook nem fut ezen a gépen. Indítsd el, és próbáld újra.");
  return t("Az Outlook-olvasás nem sikerült: {{message}}", { message });
}

export function splitAccounts(value: string): string[] {
  return value.split(",").map((a) => a.trim()).filter(Boolean);
}

/** 065: a „Korábban használt” cím hozzáadása a listához, vagy kivétele, ha már benne van. */
export function toggleAccount(value: string, account: string): string {
  const list = splitAccounts(value);
  return (list.includes(account) ? list.filter((a) => a !== account) : [...list, account]).join(", ");
}

/** 057: két helyen él. `pull`: az Új munkacsomag „postafiókból” forrása (darabszám-előnézet, letöltés most);
 *  `settings`: a Beállítások › Postafiókok (ütemezés mentése, az ütemezések és a letöltési napló). */
export function Mailbox({ variant = "settings" }: { variant?: "pull" | "settings" }) {
  useLocale();
  const data = useLoad("mailbox", api.mailbox, variant === "settings" ? 5000 : undefined);
  const [account, setAccount] = useState("");
  const [folders, setFolders] = useState("Inbox");
  const [subfolders, setSubfolders] = useState(false);
  const [mode, setMode] = useState<"recent" | "range">("recent");
  const [days, setDays] = useState(7);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [maxItems, setMaxItems] = useState(0);
  const [interval, setIntervalMin] = useState(60);
  const [preview, setPreview] = useState<MailboxCount | null>(null);
  const [busy, setBusy] = useState<"count" | "pull" | "schedule" | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "error"; text: string } | null>(null);

  const req = (): MailboxRequest => ({
    accounts: splitAccounts(account),
    folders: folders.split(",").map((f) => f.trim()).filter(Boolean),
    subfolders, max_items: maxItems,
    ...(mode === "recent" ? { since_days: days } : { received_from: from, received_to: to }),
  });

  async function act(kind: "count" | "pull" | "schedule") {
    if (kind !== "count" && !getActor()) { setMsg({ kind: "error", text: t("Nem indítható: {{reason}}.", { reason: t(NO_ACTOR) }) }); return; }
    setBusy(kind);
    setMsg(null);
    try {
      if (kind === "count") {
        setPreview(null);
        setPreview(await api.mailboxCount(req()));
      } else if (kind === "pull") {
        await api.mailboxPull(req());
        setMsg({ kind: "ok", text: t("A letöltés sorba került; a feldolgozó futtatja. Az új levelekből munkacsomag lesz, a listában megjelenik (a letöltési napló a Beállítások › Postafiókok alatt).") });
      } else {
        await api.createSchedule(req(), interval);
        setMsg({ kind: "ok", text: t("Ütemezés mentve ({{interval}}). Az első letöltés a feldolgozó következő körében indul.", { interval: intervalText(interval) }) });
      }
      data.reload();
    } catch (e) {
      const err = e as ApiError;
      setMsg({ kind: "error", text: err.code === "mailbox_unavailable" ? bridgeErrorText(err.message) : err.message });
    } finally {
      setBusy(null);
    }
  }

  const d = data.data;
  return (
    <>
      {d && !d.bridge_available ? <p className="notice error" role="alert">{t("A régi Outlook-szkript nem található a régi projektben; a letöltés nem működik.")}</p> : null}

      <form className={variant === "pull" ? "create" : "card create"} aria-label={t("Mit olvassunk")} onSubmit={(e) => { e.preventDefault(); void act("count"); }}>
        <label className="block">{t("Postafiók címe")} <span className="muted">{t("(több is, vesszővel)")}</span>
          <input value={account} onChange={(e) => { setAccount(e.target.value); setPreview(null); }} placeholder="nev@ceg.hu" required />
        </label>
        {d?.accounts?.length ? (
          // 058: a korábban használt címek egy kattintással (nem kell újra begépelni)
          <div className="chip-row" role="group" aria-label={t("Korábban használt postafiókok")}>
            <span className="muted small">{t("Korábban használt:")}</span>
            {d.accounts.map((a) => (
              // 065: hozzáad / kivesz (több cím is megadható), nem cseréli le a mezőt
              <button key={a} type="button" className="chip" aria-pressed={splitAccounts(account).includes(a)}
                onClick={() => { setAccount(toggleAccount(account, a)); setPreview(null); }}>{a}</button>
            ))}
          </div>
        ) : null}
        <div className="form-row">
          <label className="block">{t("Mappa")} <span className="muted">{t("(vesszővel)")}</span>
            <input value={folders} onChange={(e) => { setFolders(e.target.value); setPreview(null); }} />
          </label>
          <label className="check"><input type="checkbox" checked={subfolders} onChange={(e) => setSubfolders(e.target.checked)} /> {t("almappákkal")}</label>
        </div>
        <fieldset className="segmented">
          <legend className="sr-only">{t("Időszak")}</legend>
          <label><input type="radio" name="period" checked={mode === "recent"} onChange={() => { setMode("recent"); setPreview(null); }} /> {t("Az utolsó napok")}</label>
          <label><input type="radio" name="period" checked={mode === "range"} onChange={() => { setMode("range"); setPreview(null); }} /> {t("Dátumtól dátumig")}</label>
        </fieldset>
        <div className="form-row">
          {mode === "recent" ? (
            <label className="block">{t("Napok száma")}
              <input type="number" min={1} max={3650} value={days} onChange={(e) => { setDays(Number(e.target.value)); setPreview(null); }} />
            </label>
          ) : (
            <>
              <label className="block">{t("Ettől")}<input type="date" value={from} onChange={(e) => { setFrom(e.target.value); setPreview(null); }} required /></label>
              <label className="block">{t("Eddig")}<input type="date" value={to} onChange={(e) => { setTo(e.target.value); setPreview(null); }} required /></label>
            </>
          )}
          <label className="block">{t("Legfeljebb ennyi levél")} <span className="muted">{t("(0 = nincs korlát)")}</span>
            <input type="number" min={0} max={10000} value={maxItems} onChange={(e) => setMaxItems(Number(e.target.value))} />
          </label>
        </div>

        <div className="button-row">
          <button type="submit" className="secondary" disabled={busy !== null}>{busy === "count" ? t("Számolás…") : t("Hány levél? (ingyenes)")}</button>
          {variant === "pull" ? (
            <button type="button" className="primary" disabled={busy !== null || !account.trim()} onClick={() => void act("pull")}>
              {busy === "pull" ? t("Indítás…") : t("Letöltés most: új munkacsomag")}
            </button>
          ) : null}
        </div>
        {preview ? (
          <p className="notice" role="status">
            {/* 065: az új levelek száma külön; korábban az új levelek számát írta ki az időszak összes leveleként */}
            {preview.already_read
              ? t("{{total}} levél esik az időszakba: {{n}} új, {{read}} már be volt olvasva (azokat kihagyja).",
                { total: preview.in_period, n: preview.eligible, read: preview.already_read })
              : t("{{n}} új levél esik az időszakba.", { n: preview.eligible })}
            {" "}<span className="muted small">({preview.label})</span>
          </p>
        ) : null}

        {variant === "settings" ? <div className="schedule-row">
          <span className="small muted">{t("Ütemezés (csak „az utolsó napok” időszakkal):")}</span>
          <Picker label={t("Gyakoriság")} hideLabel compact value={String(interval)} onChange={(v) => setIntervalMin(Number(v))}
            options={intervals().map(([m, label]) => ({ value: String(m), label }))} />
          <button type="button" className="secondary small-btn" disabled={busy !== null || mode !== "recent" || !account.trim()}
            onClick={() => void act("schedule")}>{t("Ütemezés mentése")}</button>
        </div> : null}
        {msg ? <p className={`notice ${msg.kind === "error" ? "error" : ""}`} role={msg.kind === "error" ? "alert" : "status"}>{msg.text}</p> : null}
      </form>

      {data.error ? <p className="notice error" role="alert">{data.error.message}</p> : null}
      {variant === "settings" ? (
        <>


      <h2 className="mt">{t("Ütemezések")}</h2>
      {d && d.schedules.length === 0 ? <div className="empty">{t("Nincs ütemezés. Fent egy postafiókkal és gyakorisággal menthetsz egyet.")}</div> : null}
      {d && d.schedules.length ? (
        <table className="table">
          <thead><tr><th>{t("Mit olvas")}</th><th>{t("Gyakoriság")}</th><th>{t("Következő")}</th><th>{t("Legutóbb")}</th><th /></tr></thead>
          <tbody>
            {d.schedules.map((s) => (
              <tr key={s.id}>
                <td>{s.label}</td>
                <td>
                  <Picker label={t("Gyakoriság: {{label}}", { label: s.label })} hideLabel compact value={String(s.interval_min)}
                    options={intervals().map(([m, label]) => ({ value: String(m), label }))}
                    onChange={(v) => void api.updateSchedule(s.id, { interval_min: Number(v) }).then(data.reload, (err) => setMsg({ kind: "error", text: err.message }))} />
                </td>
                <td className="muted">{s.enabled ? when(s.next_at) : t("kikapcsolva")}</td>
                <td>{s.last_at ? <><span className={s.last_status === "error" ? "error-text" : ""}>{pullSummary({ status: s.last_status ?? "ok", result: s.last_result })}</span>
                  <div className="muted small">{when(s.last_at)}</div></> : <span className="muted">{t("még nem futott")}</span>}</td>
                <td className="right">
                  <button type="button" className="secondary small-btn" onClick={() => void api.updateSchedule(s.id, { enabled: !s.enabled }).then(data.reload, (err) => setMsg({ kind: "error", text: err.message }))}>
                    {s.enabled ? t("Kikapcsolás") : t("Bekapcsolás")}</button>{" "}
                  <button type="button" className="quiet small-btn" onClick={() => void api.deleteSchedule(s.id).then(data.reload, (err) => setMsg({ kind: "error", text: err.message }))}>{t("Törlés")}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      <p className="muted small">{t("Az ütemezés csak akkor fut, ha a feldolgozó fut, és az Outlook nyitva van ezen a gépen.")}</p>

      <h2 className="mt">{t("Letöltések")}</h2>
      <DataTable dataset="mailbox_pulls" label={t("Postafiók-letöltések")} pollMs={5000} emptyText={t("Még nem volt letöltés.")}
        cell={(col, row) => (col.key === "workpackage" && row.workpackage
          ? <a href={`#/workpackages/${encodeURIComponent(String(row.workpackage))}`}>{t("munkacsomag")}</a> : undefined)} />
        </>
      ) : null}
    </>
  );
}
