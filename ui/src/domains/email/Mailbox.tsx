// Mailbox (048 T2): what to read (mailbox, folder, period) → free count preview → a schedule (231 C3d: a download now
// is a mailbox case's, started from the new work wizard). Every download is run by the worker; the result shows in the
// download log, and the new emails become a work package with the email intent recipe (231 C3d: a mailbox case's). No
// paid processing starts by itself (decision of 2026-09-28).
import { useEffect, useState } from "react";
import { api, ApiError, getActor, NO_ACTOR, type DsColumn, type DsRow } from "../../api";
import type { MailboxCount, MailboxPull, MailboxRequest } from "./api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { DataTable } from "../../components/DataTable";
import { FormActions } from "../../components/FormActions";
import { ItemSteps } from "../../components/ItemSteps";
import { PageActions } from "../../components/PageActions";
import { Picker } from "../../components/Picker";
import { errorText, useAction, useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { intervals, when } from "../../labels";
import type { SettingsPanelProps } from "../../logic/settingsSections";
import { go, settingsHash } from "../../route";
import { settingsChanged, useSettingsTitle } from "../../views/settings/settingsTree";
import { mailboxLabel } from "./labels";
import { splitAccounts, type MailboxStepDraft } from "./mailboxSource";

export function pullSummary(p: Pick<MailboxPull, "status" | "result">): string {
  const r = p.result;
  if (p.status === "error") return r?.error ? pullErrorText(r.error) : t("Error");
  if (!r) return "–";
  const parts = [t("{{n}} new emails", { n: (r.new ?? 0) + (r.changed ?? 0) })];
  if (r.changed) parts[0] += ` ${t("({{n}} changed)", { n: r.changed })}`;
  if (r.duplicate) parts.push(t("{{n}} already present", { n: r.duplicate }));
  return parts.join(" · ");
}

/** Known errors of the legacy Outlook script in the UI language; `undefined` for anything else. */
function knownBridgeError(message: string): string | undefined {
  if (/must match exactly one Outlook account/.test(message)) {
    return t("This address does not match any Outlook account on this computer. Check the address (exactly as it appears in Outlook).");
  }
  if (/Outlook must already be running/.test(message)) return t("Outlook is not running on this computer. Start it and try again.");
  return undefined;
}

/** Error of the preview request (mailbox_unavailable): a known script error, otherwise the original text with context. */
export function bridgeErrorText(message: string): string {
  return knownBridgeError(message) ?? t("Reading from Outlook failed: {{message}}", { message });
}

/** 073: error of a finished download (download log, schedule "last run"): a known script error in the UI language,
 *  anything else unchanged (it may come from the worker, not from Outlook). */
export function pullErrorText(message: string): string {
  return knownBridgeError(message) ?? message;
}

/** 065: adds a „Korábban használt” (Previously used) address to the list, or removes it if it is already there. */
export function toggleAccount(value: string, account: string): string {
  const list = splitAccounts(value);
  return (list.includes(account) ? list.filter((a) => a !== account) : [...list, account]).join(", ");
}

/** 231 (C3d): what a mailbox download reads - the addresses (the previously used ones a click away), the folders, the
 *  period, at most how many emails - with the free count of the emails it would bring; the request, or null while it
 *  is not complete. Settings › Mailboxes saves a schedule of it; a mailbox case's general form downloads it
 *  (its chooser, `./index.tsx`). Until C3d the wizard's own download form (the `pull` variant). 261: `initial`, the
 *  request it starts from (a next period's form: the previous case's download, its range moved on). */
export function MailboxRequestFields({ onChange, initial, periods = "both" }: { onChange: (req: MailboxRequest | null) => void;
  initial?: MailboxRequest | null; periods?: "both" | "days" }) {
  useLocale();
  const data = useLoad("mailbox", api.mailbox);
  const [account, setAccount] = useState((initial?.accounts ?? []).join(", "));
  const [folders, setFolders] = useState(initial?.folders?.length ? initial.folders.join(", ") : "Inbox");
  const [subfolders, setSubfolders] = useState(!!initial?.subfolders);
  const [mode, setMode] = useState<"recent" | "range">(initial?.received_from ? "range" : "recent");
  const [days, setDays] = useState(initial?.since_days ?? 7);
  const [from, setFrom] = useState(initial?.received_from ?? "");
  const [to, setTo] = useState(initial?.received_to ?? "");
  const [maxItems, setMaxItems] = useState(initial?.max_items ?? 0);
  const [preview, setPreview] = useState<MailboxCount | null>(null);
  const [counting, setCounting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const req = (): MailboxRequest => ({
    accounts: splitAccounts(account),
    folders: folders.split(",").map((f) => f.trim()).filter(Boolean),
    subfolders, max_items: maxItems,
    ...(mode === "recent" ? { since_days: days } : { received_from: from, received_to: to }),
  });
  const complete = splitAccounts(account).length > 0 && (mode === "recent" || (!!from && !!to));
  // eslint-disable-next-line react-hooks/exhaustive-deps -- the request is told whenever a field changes
  useEffect(() => { onChange(complete ? req() : null); }, [account, folders, subfolders, mode, days, from, to, maxItems]);
  const changed = <T,>(set: (v: T) => void) => (v: T) => { set(v); setPreview(null); };

  async function count() {
    setCounting(true);
    setError(null);
    setPreview(null);
    try {
      const r = req();
      // 183: the label in the interface's language, from the request counted (the service's is English)
      setPreview({ ...(await api.mailboxCount(r)), label: mailboxLabel(r) });
    } catch (e) {
      const err = e as ApiError;
      setError(err.code === "mailbox_unavailable" ? bridgeErrorText(err.message) : err.message);
    } finally {
      setCounting(false);
    }
  }

  return (
    <div className="rc-stack">
      {data.data && !data.data.bridge_available ? <p className="notice error" role="alert">{t("The legacy Outlook script was not found in the old project; downloading does not work.")}</p> : null}
      <label className="block">{t("Mailbox address")} <span className="muted">{t("(several, comma-separated)")}</span>
        <input value={account} onChange={(e) => changed(setAccount)(e.target.value)} placeholder="nev@ceg.hu" required />
      </label>
      {data.data?.accounts?.length ? (
        // 058: the previously used addresses with a single click (no need to type them again)
        <div className="chip-row" role="group" aria-label={t("Previously used mailboxes")}>
          <span className="muted small">{t("Previously used:")}</span>
          {data.data.accounts.map((a) => (
            // 065: adds / removes (several addresses may be given), does not replace the field
            <button key={a} type="button" className="chip" aria-pressed={splitAccounts(account).includes(a)}
              onClick={() => changed(setAccount)(toggleAccount(account, a))}>{a}</button>
          ))}
        </div>
      ) : null}
      <div className="form-row">
        <label className="block">{t("Folder")} <span className="muted">{t("(comma-separated)")}</span>
          <input value={folders} placeholder="Inbox, Sent Items" onChange={(e) => changed(setFolders)(e.target.value)} />
        </label>
        <label className="check"><input type="checkbox" checked={subfolders} onChange={(e) => setSubfolders(e.target.checked)} /> {t("with subfolders")}</label>
      </div>
      {/* 264 (F6): a schedule reads the last days, never a date range (`periods="days"`) */}
      {periods === "days" ? null : <fieldset className="segmented">
        <legend className="sr-only">{t("Period")}</legend>
        <label><input type="radio" name="mailbox-period" checked={mode === "recent"} onChange={() => changed(setMode)("recent")} /> {t("The last days")}</label>
        <label><input type="radio" name="mailbox-period" checked={mode === "range"} onChange={() => changed(setMode)("range")} /> {t("Date range")}</label>
      </fieldset>}
      <div className="form-row">
        {mode === "recent" ? (
          <label className="block">{t("Number of days")}
            <input type="number" min={1} max={3650} value={days} onChange={(e) => changed(setDays)(Number(e.target.value))} />
          </label>
        ) : (
          <>
            <label className="block">{t("From")}<input type="date" value={from} onChange={(e) => changed(setFrom)(e.target.value)} required /></label>
            <label className="block">{t("Up to")}<input type="date" value={to} onChange={(e) => changed(setTo)(e.target.value)} required /></label>
          </>
        )}
        <label className="block">{t("At most this many emails")} <span className="muted">{t("(0 = no limit)")}</span>
          <input type="number" min={0} max={10000} value={maxItems} onChange={(e) => setMaxItems(Number(e.target.value))} />
        </label>
      </div>
      <div className="button-row">
        <button type="button" className="secondary" disabled={counting || !complete} onClick={() => void count()}>{counting ? t("Counting…") : t("How many emails? (free)")}</button>
      </div>
      {preview ? (
        <p className="notice" role="status">
          {/* 065: the number of new emails separately; it used to print the number of new emails as all the emails in
              the period */}
          {preview.already_read
            ? t("{{total}} emails fall in the period: {{n}} new, {{read}} already read (they will be skipped).",
              { total: preview.in_period, n: preview.eligible, read: preview.already_read })
            : t("{{n}} new emails fall in the period.", { n: preview.eligible })}
          {" "}<span className="muted small">({preview.label})</span>
        </p>
      ) : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </div>
  );
}

/** 181 / 231 (C3d): a workflow step's mailbox download in the new work wizard (its draft: the addresses, the folders, at
 *  most how many emails, the workflow's period or a number of days), found through its chooser (`./index.tsx`)
 *  (until C3d in the wizard itself). */
export function MailboxStepFields({ draft, hasPeriod, onChange }: { draft: MailboxStepDraft; hasPeriod: boolean; onChange: (patch: Partial<MailboxStepDraft>) => void }) {
  useLocale();
  const known = useLoad("mailbox", api.mailbox);
  return (
    <div className="rc-stack">
      <label className="block">{t("Mailbox address")} <span className="muted">{t("(several, comma-separated)")}</span>
        <input value={draft.accounts} onChange={(e) => onChange({ accounts: e.target.value })} placeholder="nev@ceg.hu" />
      </label>
      {known.data?.accounts?.length ? (
        <div className="chip-row" role="group" aria-label={t("Previously used mailboxes")}>
          {known.data.accounts.map((a) => (
            <button key={a} type="button" className="chip" aria-pressed={splitAccounts(draft.accounts).includes(a)}
              onClick={() => onChange({ accounts: toggleAccount(draft.accounts, a) })}>{a}</button>
          ))}
        </div>
      ) : null}
      <div className="form-row">
        <label className="block">{t("Folder")} <span className="muted">{t("(comma-separated)")}</span>
          <input value={draft.folders} onChange={(e) => onChange({ folders: e.target.value })} />
        </label>
        <label className="block">{t("At most this many emails")} <span className="muted">{t("(0 = no limit)")}</span>
          <input type="number" min={0} max={10000} value={draft.maxItems} onChange={(e) => onChange({ maxItems: Number(e.target.value) })} />
        </label>
      </div>
      {/* 181: a workflow without a period downloads by a number of days */}
      {hasPeriod ? <label className="check"><input type="checkbox" checked={draft.usePeriod} onChange={(e) => onChange({ usePeriod: e.target.checked })} /> {t("The emails received in the workflow's period")}</label> : null}
      {!draft.usePeriod || !hasPeriod ? (
        <label className="block">{t("Number of days")}
          <input type="number" min={1} max={3650} value={draft.days} onChange={(e) => onChange({ days: Number(e.target.value) })} />
        </label>
      ) : null}
    </div>
  );
}

/** Settings › Mailboxes (264, plan E, F5-F6; the owner's decision of 2026-10-31: every list the one list): the
 *  schedules are the one list, each opening its own page with its own downloads; "New schedule" is the title row's main
 *  action and has a page of its own; a one-off download (a date range too) is a new mailbox case's, its form counts and
 *  downloads (until 264 this page's form offered a date range that it could only count). The download log below. */
export function Mailbox({ item }: SettingsPanelProps) {
  useLocale();
  if (item === NEW) return <NewSchedule />;
  if (item) return <SchedulePage id={item} />;
  return <MailboxLists />;
}

const LIST = "mailbox-schedules";
const NEW = "new";

const scheduleCell = (col: DsColumn, row: DsRow) => (col.key === "label" && row._request
  // the mailbox and period in the interface's language (the service's label is English), still the link to its page
  ? <a href={settingsHash("mailboxes", row._key)}>{mailboxLabel(row._request as MailboxRequest)}</a> : undefined);

function MailboxLists() {
  useLocale();
  const data = useLoad("mailbox", api.mailbox);
  return (
    <>
      <PageActions>
        <a className="button secondary" href="#/cases/new/mailbox">{t("Download once, in a new case")}</a>
        <a className="button primary" href={settingsHash("mailboxes", NEW)}>{t("New schedule")}</a>
      </PageActions>
      {data.data && !data.data.bridge_available ? <p className="notice error" role="alert">{t("The legacy Outlook script was not found in the old project; downloading does not work.")}</p> : null}
      <h2>{t("Schedules")}</h2>
      <DataTable dataset="mailbox_schedules" label={t("Mailbox schedules")} storageId={LIST} persist={LIST} pollMs={10000}
        emptyText={t("No schedules yet: “New schedule” saves one.")} cell={scheduleCell} />
      <p className="muted small">{t("Schedules only run while the worker is running and Outlook is open on this computer.")}</p>
      <h2 className="mt">{t("Downloads")}</h2>
      <Pulls />
    </>
  );
}

/** The download log, every download's or (on a schedule's page) one schedule's. */
function Pulls({ scheduleId }: { scheduleId?: string }) {
  useLocale();
  return (
    <DataTable dataset="mailbox_pulls" label={t("Mailbox downloads")} pollMs={5000} emptyText={t("No downloads yet.")}
      {...(scheduleId ? { scope: { schedule_id: scheduleId } } : { persist: "mailbox-pulls" })}
      cell={(col, row) => (col.key === "workpackage" && row.workpackage
        ? <a href={`#/workpackages/${encodeURIComponent(String(row.workpackage))}`}>{t("document batch")}</a>
        : col.key === "error" && row.error ? pullErrorText(String(row.error))
          // 183: the mailbox and period in the interface's language (the service's label is English)
          : col.key === "label" && row._request ? mailboxLabel(row._request as MailboxRequest) : undefined)} />
  );
}

function FrequencyPicker({ value, onChange }: { value: number; onChange: (min: number) => void }) {
  useLocale();
  return (
    <Picker label={t("Frequency")} value={String(value)} onChange={(v) => onChange(Number(v))}
      options={intervals().map(([m, label]) => ({ value: String(m), label }))} />
  );
}

/** A new schedule's page: what it reads over the last days (a schedule reads relative days, never a date range), and
 *  how often; saved, it opens its own page. */
function NewSchedule() {
  useLocale();
  useSettingsTitle(t("New schedule"));
  const [request, setRequest] = useState<MailboxRequest | null>(null);
  const [interval, setIntervalMin] = useState(60);
  const { busy, error, run } = useAction();
  const actor = !!getActor();
  const save = () => request && run(() => api.createSchedule(request, interval), {
    then: (s) => { settingsChanged(); go({ view: "settings", section: "mailboxes", item: s.id }); },
    failed: (e) => (e instanceof ApiError && e.code === "mailbox_unavailable" ? bridgeErrorText(e.message) : errorText(e)),
  });
  return (
    <section className="sheet sheet-narrow" aria-label={t("New schedule")}>
      <MailboxRequestFields onChange={setRequest} periods="days" />
      <div className="form-row"><FrequencyPicker value={interval} onChange={setIntervalMin} /></div>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      <FormActions busy={busy} onCancel={() => go({ view: "settings", section: "mailboxes" })}
        note={!actor ? t("Cannot start: {{reason}}.", { reason: t(NO_ACTOR) }) : !request ? t("Give a mailbox address.") : undefined}>
        <button type="button" className="primary" disabled={busy || !request || !actor} onClick={() => void save()}>{t("Save schedule")}</button>
      </FormActions>
    </section>
  );
}

/** A schedule's page: what it reads, how often and whether it is on (saved together; Delete at the left), and its own
 *  downloads. */
function SchedulePage({ id }: { id: string }) {
  useLocale();
  const data = useLoad("mailbox", api.mailbox, 5000);
  const s = data.data?.schedules.find((x) => x.id === id);
  useSettingsTitle(s ? mailboxLabel(s.request) : null);
  const [interval, setIntervalMin] = useState<number | null>(null);
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const { busy, error, notice, run } = useAction();
  if (data.error) return <p className="notice error" role="alert">{data.error.message}</p>;
  if (!data.data) return <p className="muted">{t("Loading…")}</p>;
  if (!s) return <p className="notice warn">{t("It is not among the schedules (any more).")}</p>;
  const iv = interval ?? s.interval_min;
  const on = enabled ?? s.enabled;
  const dirty = iv !== s.interval_min || on !== s.enabled;
  const reset = () => { setIntervalMin(null); setEnabled(null); };
  const save = () => run(() => api.updateSchedule(s.id, { interval_min: iv, enabled: on }), {
    then: () => { reset(); data.reload(); settingsChanged(); }, done: t("The schedule has been saved."),
  });
  const remove = () => run(() => api.deleteSchedule(s.id), {
    then: () => { settingsChanged(); go({ view: "settings", section: "mailboxes" }); },
  });
  return (
    <>
      <PageActions><ItemSteps list={LIST} /></PageActions>
      <section className="sheet" aria-label={t("Schedule")}>
        <dl className="kv">
          <dt>{t("Reads")}</dt><dd>{mailboxLabel(s.request)}</dd>
          <dt>{t("Next")}</dt><dd>{s.enabled ? when(s.next_at) : t("off")}</dd>
          <dt>{t("Most recently")}</dt>
          <dd>{s.last_at ? <><span className={s.last_status === "error" ? "error-text" : ""}>{pullSummary({ status: s.last_status ?? "ok", result: s.last_result })}</span>
            {" "}<span className="muted small">{when(s.last_at)}</span></> : <span className="muted">{t("not run yet")}</span>}</dd>
        </dl>
        <div className="form-row"><FrequencyPicker value={iv} onChange={setIntervalMin} /></div>
        <label className="check"><input type="checkbox" checked={on} onChange={(e) => setEnabled(e.target.checked)} /> {t("On: it downloads by itself")}</label>
        {error ? <p className="notice error" role="alert">{error}</p> : null}
        {notice ? <p className="small ok" role="status">{notice}</p> : null}
        <FormActions busy={busy} onCancel={dirty ? reset : undefined}
          start={<ConfirmButton className="quiet" danger disabled={busy} question={t("Delete this schedule? Its downloads so far stay in the log.")}
            onConfirm={() => void remove()}>{t("Delete")}</ConfirmButton>}>
          <button type="button" className={dirty ? "primary" : "secondary"} disabled={!dirty || busy} onClick={() => void save()}>{t("Save")}</button>
        </FormActions>
      </section>
      <h2 className="mt">{t("Its downloads")}</h2>
      <Pulls scheduleId={s.id} />
    </>
  );
}
