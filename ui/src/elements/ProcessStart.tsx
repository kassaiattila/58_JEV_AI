// 231 (plan stage C, C1c; DECISIONS 231): starting a process pack's case that reads work packages (its scope part
// `sources`), the same way for every process: from the new work wizard (the packages of the kinds its intake takes, to
// choose) and from such a package's own page (the processes that take it, with the cases already reading it). Until
// C1c the email routing's own form and offer.
import { useEffect, useState } from "react";
import { api, ApiError, type CaseNextDraft, type CaseSource, type PackageOffer, type ProcessRecord, type StepSource } from "../api";
import { BrowseButton } from "../components/BrowseButton";
import { Icon } from "../components/Icon";
import { Picker } from "../components/Picker";
import { chooserOf } from "./sourceChoosers";
import { useAction, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { go } from "../route";

/** 231 (U2c): what a person chose as a source: a folder, files, a packet of invented documents, or a domain's source
 *  (a mailbox download); 261: a folder's or files' `onlyNew`, only the documents no live run has processed yet. */
interface SourceChoice { kind: "folder" | "files" | "example"; folder: string; recursive: boolean; files: string; packet: string;
  domain: CaseSource | null; onlyNew: boolean }
const NO_SOURCE: SourceChoice = { kind: "folder", folder: "", recursive: false, files: "", packet: "", domain: null, onlyNew: false };
/** 261: a source the next period's form starts from (the previous case's, moved on by the service). */
const choiceFrom = (s: CaseSource | undefined): SourceChoice => (!s ? NO_SOURCE
  : s.kind === "folder" ? { ...NO_SOURCE, kind: "folder", folder: s.folder ?? "", recursive: !!s.recursive, onlyNew: !!s.only_new }
  : s.kind === "files" ? { ...NO_SOURCE, kind: "files", files: (s.files ?? []).join("\n"), onlyNew: !!s.only_new }
  : { ...NO_SOURCE, domain: s });
type ChoiceUpdate = (update: (c: SourceChoice) => SourceChoice) => void;

// a path pasted with its quotes (Explorer's "Copy as path") is taken without them, as the documents form took it
const linesOf = (files: string) => files.split(/\r?\n/).map((l) => l.trim().replace(/^"|"$/g, "")).filter(Boolean);
// 231 (C3d): a maker takes a folder or files, or a source kind a domain adds (a mailbox download), chosen by its own form
const domainChooser = (kinds: string[]) => (kinds.includes("folder") || kinds.includes("files") ? undefined : chooserOf(kinds[0])?.Case);
const choiceReady = (c: SourceChoice, kinds: string[]) => (domainChooser(kinds) ? !!c.domain : c.kind === "folder" ? !!c.folder.trim()
  : c.kind === "example" ? !!c.packet : linesOf(c.files).length > 0);

/** The source as the service takes it; (U0) an example packet's documents are written as files first, and the case
 *  starts on those files. */
async function sourceOf(c: SourceChoice, kinds: string[], pack: string): Promise<CaseSource | null> {
  if (domainChooser(kinds)) return c.domain;
  if (c.kind === "example") return { kind: "files", files: (await api.examplePacketFiles(pack, c.packet)).files };
  const onlyNew = c.onlyNew ? { only_new: true } : {};  // 261
  return c.kind === "folder" ? { kind: "folder", folder: c.folder.trim(), recursive: c.recursive, ...onlyNew }
    : { kind: "files", files: linesOf(c.files), ...onlyNew };
}

/** The wizard's form of a one-step template of a process pack's case: what its scope asks a person (the packages it
 *  reads; 231 C2d: its own party and period; the other parts take their default, e.g. the party's accounts) and its
 *  name; (U2c) for a process whose steps run cases of other processes, each such step's own documents. 261: `after`, the
 *  case whose next period it starts: the form is filled in from it (the service's draft) and the new case follows it. */
export function ProcessCreate({ pack, onDone, after }: { pack: string; onDone: (wpId: string) => void; after?: string }) {
  useLocale();
  const draft = useLoad(after ? `case-next:${after}` : null, () => api.caseNext(after ?? ""));
  if (!after) return <ProcessForm pack={pack} onDone={onDone} />;
  if (draft.error) return <p className="notice error" role="alert">{draft.error.message}</p>;
  if (!draft.data) return <p className="muted">{t("Loading…")}</p>;
  return <ProcessForm pack={pack} onDone={onDone} draft={draft.data} />;
}

function ProcessForm({ pack, onDone, draft }: { pack: string; onDone: (wpId: string) => void; draft?: CaseNextDraft }) {
  useLocale();
  const packs = useLoad("processes", api.processes);
  const list = useLoad("workpackages-brief", api.workpackagesBrief);
  const parties = useLoad("own-parties", api.ownParties);
  const [chosen, setChosen] = useState<string[]>([]);
  const [partyId, setPartyId] = useState(draft?.party_id ?? "");
  const [start, setStart] = useState(draft?.period_start ?? "");
  const [end, setEnd] = useState(draft?.period_end ?? "");
  const [name, setName] = useState(draft?.name ?? "");
  // 231 (C3b3): the documents of a document processing case (its scope part `source`); (U0) or a packet of the
  // process's invented example documents; (C3d) or a domain's source kind's
  const [choice, setChoice] = useState<SourceChoice>(() => choiceFrom(draft?.source));
  const [stepChoices, setStepChoices] = useState<Record<string, SourceChoice>>(  // 231 (U2c): by step
    () => Object.fromEntries(Object.entries(draft?.step_sources ?? {}).map(([step, s]) => [step, choiceFrom(s)])));
  const [record, setRecord] = useState<ProcessRecord | null>(null);  // 231 (C3c): the record the case starts from
  const { busy, error, run } = useAction();
  const info = packs.data?.processes.find((p) => p.id === pack);
  const examples = useLoad(info?.examples ? `examples:${pack}` : null, () => api.processExamples(pack));  // 231 (U0)
  const packets = examples.data?.packets ?? [];
  if (packs.error) return <p className="notice error" role="alert">{packs.error.message}</p>;
  if (!info) return <p className="muted">{t("Loading…")}</p>;
  const title = t(info.title);
  const asks = info.asks ?? info.scope ?? [];
  const wantsSources = asks.includes("sources");
  const wantsParty = asks.includes("party");
  const wantsPeriod = asks.includes("period");
  const wantsSource = asks.includes("source");
  const wantsRecord = asks.includes("record");
  const steps = asks.includes("step_sources") ? info.step_sources ?? [] : [];
  const kinds = info.source_kinds ?? ["folder", "files"];
  const packetTitle = packets.find((x) => x.id === choice.packet)?.title;
  const candidates = (list.data?.workpackages ?? []).filter((w) => (info.package_kinds ?? []).includes(w.source_kind));
  const partyName = (parties.data?.parties ?? []).find((p) => p.id === partyId)?.name ?? "";
  const ready = (!wantsSources || chosen.length > 0) && (!wantsParty || !!partyId) && (!wantsPeriod || (!!start && !!end && start <= end))
    && (!wantsSource || choiceReady(choice, kinds)) && (!wantsRecord || !!record)
    && steps.every((x) => choiceReady(stepChoices[x.step] ?? NO_SOURCE, x.source_kinds));
  const defaultName = () => {
    if (wantsSources) return `${title}: ${candidates.filter((w) => chosen.includes(w.id)).map((w) => w.name).join(", ")}`;
    if (wantsRecord && record) return `${title}: ${record.name ?? record.label ?? record.workpackage_name}`;
    if (wantsSource && !domainChooser(kinds) && choice.kind === "example" && packetTitle) return `${title} · ${t("Example")}: ${t(packetTitle)}`;
    // 231 (U3, the backlog's mailbox case name): a domain's source in its own words (the mailbox and the period)
    const words = wantsSource && domainChooser(kinds) && choice.domain ? chooserOf(kinds[0])?.name?.(choice.domain) : undefined;
    if (words) return `${title} · ${words}`;
    const where = wantsSource && !domainChooser(kinds) && choice.kind === "folder" ? choice.folder.trim().split(/[\\/]/).filter(Boolean).pop() ?? "" : "";
    return [title, partyName, wantsPeriod ? `${start} – ${end}` : "", where].filter(Boolean).join(" · ");
  };
  const submit = () => run(async () => {
    const documents = wantsSource ? await sourceOf(choice, kinds, pack) : null;
    const bySteps: Record<string, CaseSource> = {};
    for (const x of steps) {
      const given = await sourceOf(stepChoices[x.step] ?? NO_SOURCE, x.source_kinds, x.pack);
      if (given) bySteps[x.step] = given;
    }
    return api.startCase({
      pack, name: (name.trim() || defaultName()).slice(0, 200),
      ...(wantsSources ? { sources: chosen } : {}), ...(wantsParty ? { party_id: partyId } : {}),
      ...(wantsPeriod ? { period_start: start, period_end: end } : {}), ...(wantsSource && documents ? { source: documents } : {}),
      ...(wantsRecord && record ? { record: { workpackage_id: record.workpackage_id, item_id: record.item_id } } : {}),
      ...(steps.length ? { step_sources: bySteps } : {}), ...(draft ? { follows: draft.follows } : {}),
    });
  }, { then: (made) => onDone(made.case_id) });
  return (
    <form className="create rc-stack" aria-label={title} onSubmit={(e) => { e.preventDefault(); if (ready) void submit(); }}>
      {draft ? (
        <p className="small muted">{t("Filled in from the previous period's case.")}{" "}
          <a className="mono" href={`#/cases/${encodeURIComponent(draft.follows)}`}>{draft.follows}</a></p>
      ) : null}
      {list.error ? <p className="notice error" role="alert">{list.error.message}</p> : null}
      {wantsRecord ? <RecordChooser pack={pack} chosen={record} onChoose={setRecord} /> : null}
      {wantsSources ? (
        <fieldset className="wizard-choices">
          <legend>{t("The packages the case reads")}</legend>
          {candidates.length ? candidates.map((w) => (
            <label key={w.id} className="check">
              <input type="checkbox" checked={chosen.includes(w.id)}
                onChange={(e) => setChosen((prev) => (e.target.checked ? [...prev, w.id] : prev.filter((x) => x !== w.id)))} /> {w.name}
            </label>
          )) : <p className="muted small">{list.data ? t("No package this process reads yet.") : t("Loading…")}</p>}
        </fieldset>
      ) : null}
      {wantsParty ? (
        <label className="block">{t("Own party")}
          <select value={partyId} onChange={(e) => setPartyId(e.target.value)} required>
            <option value="">{t("Choose…")}</option>
            {(parties.data?.parties ?? []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
      ) : null}
      {parties.error ? <p className="notice error small" role="alert">{parties.error.message}</p> : null}
      {wantsPeriod ? (
        <div className="rc-period">
          <label className="block">{t("Period from")}<input type="date" value={start} required onChange={(e) => setStart(e.target.value)} /></label>
          <label className="block">{t("to")}<input type="date" value={end} required onChange={(e) => setEnd(e.target.value)} /></label>
        </div>
      ) : null}
      {wantsSource ? (
        <SourceFields legend={t("The case's documents")} name="case-source" kinds={kinds} packets={packets} choice={choice}
          onChange={setChoice} offerOnlyNew={!!draft} />
      ) : null}
      {steps.map((x) => (
        <StepSourceFields key={x.step} entry={x} choice={stepChoices[x.step] ?? NO_SOURCE} offerOnlyNew={!!draft}
          onChange={(update) => setStepChoices((prev) => ({ ...prev, [x.step]: update(prev[x.step] ?? NO_SOURCE) }))} />
      ))}
      <label className="block">{t("Name")} <span className="muted">{t("(optional)")}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
      </label>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      <div className="button-row">
        <button type="submit" className="primary" disabled={busy || !ready}>{busy ? t("Creating…") : t("Create")}</button>
      </div>
    </form>
  );
}

/** 231 (U2c): a step's own documents, for the case of another process it runs (that process's invented documents to
 *  start on, where it has some). */
function StepSourceFields({ entry, choice, onChange, offerOnlyNew }: { entry: StepSource; choice: SourceChoice; onChange: ChoiceUpdate;
  offerOnlyNew?: boolean }) {
  useLocale();
  const examples = useLoad(entry.examples ? `examples:${entry.pack}` : null, () => api.processExamples(entry.pack));
  return (
    <SourceFields legend={`${t(entry.title)} · ${t(entry.process)}`} name={`case-source-${entry.step}`} kinds={entry.source_kinds}
      packets={examples.data?.packets ?? []} choice={choice} onChange={onChange} offerOnlyNew={offerOnlyNew} />
  );
}

/** Where documents come from: a domain's own chooser (a mailbox download), or a folder, chosen files or a packet of
 *  invented documents. 261: in a next period's form a folder or files may take only the new documents (`offerOnlyNew`). */
function SourceFields({ legend, name, kinds, packets, choice, onChange, offerOnlyNew }: { legend: string; name: string; kinds: string[];
  packets: { id: string; title: string; documents: number }[]; choice: SourceChoice; onChange: ChoiceUpdate; offerOnlyNew?: boolean }) {
  useLocale();
  const set = (over: Partial<SourceChoice>) => onChange((c) => ({ ...c, ...over }));
  const Chooser = domainChooser(kinds);
  const fileLines = linesOf(choice.files);
  // the picked files go after the lines already there, each path only once (081)
  const addFiles = (picked: string[]) => {
    const seen = new Set(fileLines.map((f) => f.toLowerCase()));
    set({ files: [...fileLines, ...picked.filter((f) => !seen.has(f.toLowerCase()))].join("\n") });
  };
  if (Chooser) {
    return (
      <fieldset className="wizard-choices">
        <legend>{legend}</legend>
        <Chooser initial={choice.domain} onChange={(domain) => set({ domain })} />
      </fieldset>
    );
  }
  return (
    <fieldset className="wizard-choices">
      <legend>{legend}</legend>
      <div className="segmented" role="radiogroup" aria-label={t("Source")}>
        <label><input type="radio" name={name} checked={choice.kind === "folder"} onChange={() => set({ kind: "folder" })} /> {t("Documents from a folder")}</label>
        <label><input type="radio" name={name} checked={choice.kind === "files"} onChange={() => set({ kind: "files" })} /> {t("Chosen files")}</label>
        {packets.length ? (
          <label><input type="radio" name={name} checked={choice.kind === "example"} onChange={() => set({ kind: "example" })} /> {t("Example documents")}</label>
        ) : null}
      </div>
      {choice.kind === "example" ? (
        <label className="block">{t("The packet of invented documents")}
          <select value={choice.packet} onChange={(e) => set({ packet: e.target.value })} required>
            <option value="">{t("Choose…")}</option>
            {packets.map((x) => (
              <option key={x.id} value={x.id}>{t(x.title)} ({t("{{n}} documents", { n: x.documents })})</option>
            ))}
          </select>
        </label>
      ) : choice.kind === "folder" ? (
        <>
          <div className="path-row">
            <label className="block grow">{t("The folder's full path")}
              <input value={choice.folder} onChange={(e) => set({ folder: e.target.value })} required />
            </label>
            <BrowseButton kind="folder" initial={choice.folder} onPick={([p]) => set({ folder: p })} />
          </div>
          <label className="check"><input type="checkbox" checked={choice.recursive} onChange={(e) => set({ recursive: e.target.checked })} /> {t("Its subfolders too")}</label>
        </>
      ) : (
        <div className="path-row">
          <label className="block grow">{t("The files' full paths, one a line")}
            <textarea value={choice.files} onChange={(e) => set({ files: e.target.value })} rows={4} required />
          </label>
          <BrowseButton kind="files" initial={fileLines[fileLines.length - 1]} onPick={addFiles} />
        </div>
      )}
      {offerOnlyNew && choice.kind !== "example" ? (
        <label className="check"><input type="checkbox" checked={choice.onlyNew} onChange={(e) => set({ onlyNew: e.target.checked })} /> {t("Only the documents no live run has processed yet")}</label>
      ) : null}
    </fieldset>
  );
}

/** 231 (C3c): the record a case starts from (the pack's record step reads it: a quote request, an email or a document
 *  read as one), chosen from the service's search; the cases already started from it are linked. Until C3c the quote's
 *  own form. */
function RecordChooser({ pack, chosen, onChoose }: { pack: string; chosen: ProcessRecord | null; onChoose: (r: ProcessRecord | null) => void }) {
  useLocale();
  const [q, setQ] = useState("");
  const [found, setFound] = useState<ProcessRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {  // the service searches; a short pause between keys keeps it from asking at every key
    let live = true;
    const timer = window.setTimeout(() => {
      api.processRecords(pack, q.trim() || undefined)
        .then((r) => { if (live) setFound(r.records); })
        .catch((e) => { if (live) setError(e instanceof ApiError ? e.message : String(e)); });
    }, q ? 250 : 0);
    return () => { live = false; window.clearTimeout(timer); };
  }, [pack, q]);
  const key = (r: ProcessRecord) => `${r.workpackage_id}|${r.item_id}`;
  const label = (r: ProcessRecord) => r.label ?? t("(no subject)");
  return (
    <div className="rc-stack">
      <Picker label={t("The case's record")} value={chosen ? key(chosen) : null} loading={found === null} onSearch={setQ}
        options={(found ?? []).map((r) => ({ value: key(r), label: label(r), detail: r.detail }))}
        placeholder={t("Choose a record…")} selectedLabel={chosen ? label(chosen) : undefined}
        emptyText={q ? t("No record matches.") : t("No record to start from yet: an email or a document read as one in a processed package.")}
        onChange={(v) => onChoose((found ?? []).find((r) => key(r) === v) ?? null)} />
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      {chosen ? (
        <div className="small">
          <p>{t("its package:")}{" "}
            <a href={`#/workpackages/${encodeURIComponent(chosen.workpackage_id)}`}>{chosen.workpackage_name}</a></p>
          {chosen.cases.length ? (
            <p className="warn-text">{t("Cases already started from it:")}{" "}
              {chosen.cases.map((c, i) => (
                <span key={c.id}>{i ? ", " : ""}<a href={`#/cases/${encodeURIComponent(c.id)}`}>{c.name}</a></span>
              ))}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** A package's page: the processes whose case may read it (`jav/app/intake.py` `package_offers`), each started with one
 *  click; the cases already reading it are linked. */
export function PackageIntake({ offers }: { offers: PackageOffer[] }) {
  return <>{offers.map((o) => <PackageOfferCard key={o.pack} offer={o} />)}</>;
}

function PackageOfferCard({ offer: o }: { offer: PackageOffer }) {
  useLocale();
  const { busy, error, run } = useAction();
  const title = t(o.title);
  // U1: the case is named with the process's title in the interface's language (the service's name has its English one)
  const name = o.package_name ? `${title}: ${o.package_name}`.slice(0, 200) : o.name;
  const start = () => run(() => api.startCase({ pack: o.pack, name, sources: o.sources }),
    { then: (made) => go({ view: "cases", caseId: made.case_id }) });
  return (
    <section className="card rc-stack" aria-label={title}>
      <div className="button-row">
        <p className="small grow"><strong>{title}</strong> · {t("A case of this process reads this package.")}</p>
        <button type="button" className="secondary" disabled={busy} onClick={() => void start()}><Icon name="plus" />{t("Start a case")}</button>
      </div>
      {o.cases.length ? (
        <p className="small">{t("Cases reading it:")} {o.cases.map((c, i) => (
          <span key={c.id}>{i ? ", " : ""}<a href={`#/cases/${encodeURIComponent(c.id)}`}>{c.name}</a></span>
        ))}</p>
      ) : null}
      {error ? <p className="notice error" role="alert">{error}</p> : null}
    </section>
  );
}
