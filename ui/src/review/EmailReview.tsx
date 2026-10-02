// Review of an email item (048 T2): the email on the left (header, attachments, body), the recognised intent, the
// proposed next step and the to-dos on the right. There are no extracted fields or page images here; the attachments
// can be processed separately as documents.
import { useEffect, useState } from "react";
import { api, ApiError, type ItemResult, type RejectedTask } from "../api";
import { Icon } from "../components/Icon";
import { Picker } from "../components/Picker";
import { getLocale, t, useLocale } from "../i18n";
import { docTypeLabel, intentLabel, intentOptions, nextFlowText, reasonText, TASK_ACTION, tmap, when } from "../labels";
import { Split } from "./Split";
import { useResolve } from "./useResolve";

export function EmailReview({ data, onChanged, wpId }: { data: ItemResult; onChanged: () => void; wpId?: string }) {
  useLocale();
  const m = data.email!;
  const r = m.result;
  const { resolve, pending: resolving, error: resolveError } = useResolve(onChanged);
  return (
    <Split
      left={
        <article className="mail-view" aria-label={t("A levél")}>
          {/* 086 (audit N04): the email as the item was added, never a later version's text */}
          {m.source_status === "changed" ? (
            <p className="notice error" role="alert">{t("A levélnek az a változata, amelyet ez a tétel feldolgozott, már nem található; ezért a szövege nem jeleníthető meg.")}</p>
          ) : m.source_status === "earlier" ? (
            <p className="notice">{t("Ez a levél azóta módosult tartalommal újra beérkezett; itt a feldolgozott változata látszik.")}</p>
          ) : null}
          <h2>{m.subject || <span className="muted">{t("(tárgy nélkül)")}</span>}</h2>
          <dl className="mail-meta">
            <dt>{t("Feladó")}</dt><dd>{m.sender_name ? `${m.sender_name} <${m.sender ?? ""}>` : m.sender ?? "–"}</dd>
            <dt>{t("Címzett")}</dt><dd>{m.to.join(", ") || "–"}</dd>
            <dt>{t("Érkezett")}</dt><dd>{when(m.received_at)}</dd>
            <dt>{t("Csatolmány")}</dt><dd>{m.attachments.length ? m.attachments.join(", ") : t("nincs")}</dd>
          </dl>
          <BodyCoverage c={m.body_coverage} />
          <div className="mail-body">{m.body ? <MailText text={m.body} /> : <span className="muted">{t("(üres levél)")}</span>}</div>
        </article>
      }
      right={
        <section className="panel" aria-label={t("Szándék és teendők")}>
          {resolveError ? <p className="notice error" role="alert">{resolveError}</p> : null}
          {data.open_reasons.length ? (
            <ul className="issues" aria-label={t("Nyitott teendők ebben a futásban")}>
              {data.open_reasons.map((x) => (
                <li key={x.id} className="issue"><span>{reasonText(x.reason)}</span>
                  <button type="button" className="secondary small-btn" disabled={resolving !== null} onClick={() => void resolve(x)}><Icon name="check" />{t("Rendezve")}</button></li>
              ))}
            </ul>
          ) : <p className="ok pad-s">{t("Ebben a futásban nincs nyitott teendő ezen a levélen.")}</p>}
          {r ? (
            <div className="intent-box">
              <div className="muted small">{t("Felismert szándék")}</div>
              <div className="intent">{r.intent ? intentLabel(r.intent) : r.intent_label ?? t("nem sikerült felismerni")}</div>
              {r.corrected ? (
                <div className="small">{r.machine_intent && r.machine_intent !== r.intent
                  ? t("Kézzel javítva (a gép szerint: {{intent}})", { intent: intentLabel(r.machine_intent) })
                  : t("Kézzel megerősítve")}</div>
              ) : r.confidence != null ? <div className="small">{t("Modellbecslés: {{p}}%", { p: Math.round(r.confidence * 100) })}</div> : null}
              <IntentEditor data={data} onChanged={onChanged} />
              <TasksPanel data={data} onChanged={onChanged} />
              <div className="small mt-s">{t("Javasolt következő lépés:")} <strong>{nextFlowText(r.next_flow)}</strong></div>
              {!r.from_this_run ? <p className="notice small mt-s">{t("Ez az eredmény egy későbbi futásból való ugyanerről a levélről.")}</p> : null}
            </div>
          ) : <p className="muted pad-s">{t("A levelet ez a futás még nem dolgozta fel.")}</p>}
          {r && r.attachments.length ? (
            <div className="pad-s">
              <div className="muted small">{t("Csatolmányok felismerése")}</div>
              <ul className="plain small">
                {r.attachments.map((a, i) => <li key={i}>{a.filename}: {a.doc_type ? docTypeLabel(a.doc_type) : a.status ? ATTACHMENT_STATUS[a.status] ?? a.status : "–"}</li>)}
              </ul>
            </div>
          ) : null}
          {data.attachment_items?.length ? (
            // 058 K5.2: the attachment ran as a document in this run: the extraction result is in its own view
            <div className="pad-s">
              <div className="muted small">{t("A csatolmányok adatai")}</div>
              <ul className="plain small">
                {data.attachment_items.map((a) => (
                  <li key={a.item_id}><a href={wpId ? `#/workpackages/${wpId}/review/${encodeURIComponent(a.item_id)}` : undefined}>{t("{{file}}: az adatkinyerés eredménye", { file: a.filename })} →</a></li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      }
    />
  );
}

/** 058 K5.1: manual correction of the intent. The correction is versioned (like a document's fields); saving closes the
 *  run's own intent to-dos, and the routing is computed from the corrected intent. It cannot be corrected on an
 *  approved run. */
function IntentEditor({ data, onChanged }: { data: ItemResult; onChanged: () => void }) {
  useLocale();
  const current = data.email?.result?.intent ?? null;
  const [value, setValue] = useState<string | null>(current);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setValue(current), [current, data.item_id]);
  const save = async () => {
    if (!value) return;
    setBusy(true);
    setError(null);
    try {
      await api.saveCorrection(data.run_id, data.item_id, { fields: { intent: value }, expected_revision: data.correction.revision });
      onChanged();
    } catch (e) {
      const err = e as ApiError;
      setError(err.status === 409 ? t("Közben más is javította ezt a levelet. Frissítettük; nézd át és mentsd újra.") : err.message);
      onChanged();
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="intent-edit mt-s">
      <Picker label={t("Szándék javítása")} value={value} options={intentOptions()} onChange={setValue} />
      <button type="button" className="secondary small-btn" disabled={busy || !value || (value === current && !!data.email?.result?.corrected)}
        onClick={() => void save()}>{value === current ? t("Megerősítés") : t("Javítás mentése")}</button>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </div>
  );
}

/** 058 K5.3: the task proposals (after the evidence gate in code). A proposal is only a proposal: only a person can
 *  accept or reject it; once they have decided on all of them, the email's „javaslat vár döntésre” (proposal awaiting
 *  a decision) to-do is closed. */
function TasksPanel({ data, onChanged }: { data: ItemResult; onChanged: () => void }) {
  useLocale();
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tv = data.email?.tasks;
  if (!tv) return null;
  if (tv.status === "skipped") return <p className="muted small mt-s">{t("Feladatjavaslat: archiválandó levélen nem kértünk.")}</p>;
  if (tv.status === "error") return <p className="notice error small mt-s">{t("A feladatjavaslat nem készült el ({{why}}); a teendők között látszik.", { why: tv.error ?? "?" })}</p>;
  const decide = async (index: number, decision: "accepted" | "rejected" | "done" | "undone") => {
    setBusy(index);
    setError(null);
    try {
      if (decision === "done" || decision === "undone") await api.markTaskDone(data.run_id, data.item_id, index, decision === "done");
      else await api.decideTask(data.run_id, data.item_id, index, decision);
      onChanged();
    } catch (e) {
      setError((e as ApiError).message);
    } finally {
      setBusy(null);
    }
  };
  return (
    <div className="task-box mt-s">
      <div className="muted small">{t("Feladatjavaslatok (elfogadni csak ember tud)")}</div>
      {tv.tasks.length === 0 ? <p className="small">{t("A levélből nem adódik teendő.")}</p> : (
        <ul className="plain task-list">
          {tv.tasks.map((tk) => (
            <li key={tk.index} className="task-item">
              <div><strong>{tk.title}</strong> <span className="muted small">· {TASK_ACTION[tk.action] ?? tk.action}</span>
                {tk.merged ? <span className="muted small"> · {t("{{n}} azonos javaslat összevonva", { n: tk.merged + 1 })}</span> : null}</div>
              {tk.due_date ? <div className="small">{t("Határidő: {{date}}", { date: tk.due_date })}</div> : null}
              {tk.assignee_hint ? <div className="small">{t("Felelős: {{who}}", { who: tk.assignee_hint })}</div> : null}
              <div className="small muted">{t("Bizonyíték:")} {tk.evidence.map((e) => `„${e.quote}”`).join(" · ")}</div>
              {tk.decision ? (
                <div className="small">{tk.decision.decision === "accepted"
                  ? t("Elfogadta: {{who}}", { who: tk.decision.actor }) : t("Elvetette: {{who}}", { who: tk.decision.actor })}</div>
              ) : null}
              {tk.decision?.done_at ? (
                <div className="small"><strong>{t("Elvégezte: {{who}}, {{when}}", { who: tk.decision.done_by ?? "", when: when(tk.decision.done_at) })}</strong></div>
              ) : null}
              <div className="button-row">
                <button type="button" className="secondary small-btn" disabled={busy !== null || tk.decision?.decision === "accepted"}
                  onClick={() => void decide(tk.index, "accepted")}><Icon name="check" />{t("Elfogadás")}</button>
                <button type="button" className="quiet small-btn" disabled={busy !== null || tk.decision?.decision === "rejected"}
                  onClick={() => void decide(tk.index, "rejected")}>{t("Elvetés")}</button>
                {tk.decision?.decision === "accepted" ? (tk.decision.done_at
                  ? <button type="button" className="quiet small-btn" disabled={busy !== null} onClick={() => void decide(tk.index, "undone")}>{t("Elvégzés visszavonása")}</button>
                  : <button type="button" className="secondary small-btn" disabled={busy !== null} onClick={() => void decide(tk.index, "done")}><Icon name="check" />{t("Elvégezve")}</button>) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
      {tv.rejected.length ? <RejectedTasks rejected={tv.rejected} /> : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </div>
  );
}

/** 062: the content of the dropped proposals and the parts that failed, so that one can judge whether dropping them
 *  was justified. */
function RejectedTasks({ rejected }: { rejected: RejectedTask[] }) {
  useLocale();
  const partLabel: Record<string, string> = {
    task: t("a teendő (ismeretlen fajta vagy üres cím)"), evidence: t("a teendő bizonyítéka"), due_date: t("a határidő"), assignee: t("a felelős"),
  };
  return (
    <details className="small mt-s">
      <summary className="muted">{t("{{n}} javaslat kiesett a bizonyíték-ellenőrzésen (nem szó szerinti idézet, kitalált határidő vagy felelős).", { n: rejected.length })}</summary>
      <ul className="plain task-list">
        {rejected.map((r, n) => (
          <li key={r.index ?? `x${n}`} className="task-item">
            {r.title ? (
              <>
                <div><strong>{r.title}</strong>{r.action ? <span className="muted"> · {TASK_ACTION[r.action] ?? r.action}</span> : null}</div>
                {r.due_date ? <div>{t("Határidő: {{date}}", { date: r.due_date })}</div> : null}
                {r.assignee_hint ? <div>{t("Felelős: {{who}}", { who: r.assignee_hint })}</div> : null}
                {r.failed_parts?.length ? <div>{t("Nem igazolható: {{parts}}", { parts: r.failed_parts.map((p) => partLabel[p] ?? p).join(", ") })}</div> : null}
                {(r.quotes ?? []).map((q, k) => (
                  <div key={k} className={q.ok ? "muted" : undefined}>
                    „{q.quote}” – {q.ok ? t("szó szerint megvan") : t("nem áll szó szerint a levélben")}
                  </div>
                ))}
              </>
            ) : <div className="muted">{t("A javaslat szövege ennél a korábbi futásnál nem maradt meg.")}</div>}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** 058 K5.1: how much of the email body the intent recognition saw (the end of the email may only be missing if this
 *  is flagged). */
function BodyCoverage({ c }: { c?: NonNullable<ItemResult["email"]>["body_coverage"] }) {
  useLocale();
  if (!c) return null;
  if (c.status === "capped") {
    return <p className="notice error small">{t("A levél szövege a letöltéskor elvágódhatott ({{n}} karakternél): a vége hiányozhat, a szándék-felismerés sem látta.", { n: c.chars.toLocaleString(getLocale()) })}</p>;
  }
  if (c.status === "shortened") {
    return <p className="notice small">{t("A szándék-felismerés a levél szövegének csak az elejét látta: {{seen}} / {{all}} karakter.", { seen: c.seen_chars.toLocaleString(getLocale()), all: c.own_chars.toLocaleString(getLocale()) })}</p>;
  }
  return c.quoted_removed ? <p className="muted small">{t("A szándék-felismerés a levél teljes saját szövegét látta; az idézett korábbi levelet nem.")}</p> : null;
}

// 058: the processing status of the attachment in everyday words (instead of the local service's code)
const ATTACHMENT_STATUS: Record<string, string> = tmap({
  unsupported: "nem olvasható (kép vagy más formátum)",
  name_only: "csak a neve ismert",
  needs_ocr: "szövegfelismerés kell",
  unreadable: "a PDF nem olvasható (sérült vagy túl nagy)",
});

const URL_RE = /<?(https?:\/\/[^\s<>"]+)>?/g;

/** Splits the email body into pieces: plain text and links (the host name is shown in place of the link). */
export function splitLinks(text: string): ({ text: string } | { url: string; host: string })[] {
  const out: ({ text: string } | { url: string; host: string })[] = [];
  let last = 0;
  for (const m of text.matchAll(URL_RE)) {
    if (m.index! > last) out.push({ text: text.slice(last, m.index) });
    let host = m[1];
    try {
      host = new URL(m[1]).host;
    } catch {
      /* malformed link: the full text stays */
    }
    out.push({ url: m[1], host });
    last = m.index! + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last) });
  return out;
}

/** 058: a short marker instead of long tracking links (the host name, with the full address in the tooltip). The link
 *  is deliberately not clickable: the UI does not open links from an outside email. */
function MailText({ text }: { text: string }) {
  useLocale();
  return (
    <>
      {splitLinks(text).map((part, i) => ("url" in part
        ? <span key={i} className="mail-link" title={part.url}>{t("link: {{host}}", { host: part.host })}</span>
        : <span key={i}>{part.text}</span>))}
    </>
  );
}
