// 231 (plan stage C, C1c; DECISIONS 231): starting a process pack's case that reads work packages (its scope part
// `sources`), the same way for every process: from the new work wizard (the packages of the kinds its intake takes, to
// choose) and from such a package's own page (the processes that take it, with the cases already reading it). Until
// C1c the email routing's own form and offer.
import { useState } from "react";
import { api, type CaseSource, type PackageOffer } from "../api";
import { BrowseButton } from "../components/BrowseButton";
import { Icon } from "../components/Icon";
import { useAction, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { go } from "../route";

/** The wizard's form of a one-step template of a process pack's case: what its scope asks a person (the packages it
 *  reads; 231 C2d: its own party and period; the other parts take their default, e.g. the party's accounts) and its
 *  name. */
export function ProcessCreate({ pack, onDone }: { pack: string; onDone: (wpId: string) => void }) {
  useLocale();
  const packs = useLoad("processes", api.processes);
  const list = useLoad("workpackages-brief", api.workpackagesBrief);
  const parties = useLoad("parties", api.parties);
  const [chosen, setChosen] = useState<string[]>([]);
  const [partyId, setPartyId] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [name, setName] = useState("");
  // 231 (C3b3): the documents of a document processing case (its scope part `source`)
  const [sourceKind, setSourceKind] = useState<"folder" | "files">("folder");
  const [folder, setFolder] = useState("");
  const [recursive, setRecursive] = useState(false);
  const [files, setFiles] = useState("");
  const { busy, error, run } = useAction();
  const info = packs.data?.processes.find((p) => p.id === pack);
  if (packs.error) return <p className="notice error" role="alert">{packs.error.message}</p>;
  if (!info) return <p className="muted">{t("Loading…")}</p>;
  const title = t(info.title);
  const asks = info.asks ?? info.scope ?? [];
  const wantsSources = asks.includes("sources");
  const wantsParty = asks.includes("party");
  const wantsPeriod = asks.includes("period");
  const wantsSource = asks.includes("source");
  // a path pasted with its quotes (Explorer's "Copy as path") is taken without them, as the documents form took it
  const fileLines = files.split(/\r?\n/).map((l) => l.trim().replace(/^"|"$/g, "")).filter(Boolean);
  // the picked files go after the lines already there, each path only once (081)
  const addFiles = (picked: string[]) => {
    const seen = new Set(fileLines.map((f) => f.toLowerCase()));
    setFiles([...fileLines, ...picked.filter((f) => !seen.has(f.toLowerCase()))].join("\n"));
  };
  const source: CaseSource = sourceKind === "folder" ? { kind: "folder", folder: folder.trim(), recursive } : { kind: "files", files: fileLines };
  const hasSource = sourceKind === "folder" ? !!folder.trim() : fileLines.length > 0;
  const candidates = (list.data?.workpackages ?? []).filter((w) => (info.package_kinds ?? []).includes(w.source_kind));
  const partyName = (parties.data?.parties ?? []).find((p) => p.id === partyId)?.name ?? "";
  const ready = (!wantsSources || chosen.length > 0) && (!wantsParty || !!partyId) && (!wantsPeriod || (!!start && !!end && start <= end))
    && (!wantsSource || hasSource);
  const defaultName = () => {
    if (wantsSources) return `${title}: ${candidates.filter((w) => chosen.includes(w.id)).map((w) => w.name).join(", ")}`;
    const where = wantsSource ? (sourceKind === "folder" ? folder.trim().split(/[\\/]/).filter(Boolean).pop() ?? "" : "") : "";
    return [title, partyName, wantsPeriod ? `${start} – ${end}` : "", where].filter(Boolean).join(" · ");
  };
  const submit = () => run(() => api.startCase({
    pack, name: (name.trim() || defaultName()).slice(0, 200),
    ...(wantsSources ? { sources: chosen } : {}), ...(wantsParty ? { party_id: partyId } : {}),
    ...(wantsPeriod ? { period_start: start, period_end: end } : {}), ...(wantsSource ? { source } : {}),
  }), { then: (made) => onDone(made.case_id) });
  return (
    <form className="create rc-stack" aria-label={title} onSubmit={(e) => { e.preventDefault(); if (ready) void submit(); }}>
      {list.error ? <p className="notice error" role="alert">{list.error.message}</p> : null}
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
        <fieldset className="wizard-choices">
          <legend>{t("The case's documents")}</legend>
          <div className="segmented" role="radiogroup" aria-label={t("Source")}>
            <label><input type="radio" name="case-source" checked={sourceKind === "folder"} onChange={() => setSourceKind("folder")} /> {t("Documents from a folder")}</label>
            <label><input type="radio" name="case-source" checked={sourceKind === "files"} onChange={() => setSourceKind("files")} /> {t("Chosen files")}</label>
          </div>
          {sourceKind === "folder" ? (
            <>
              <div className="path-row">
                <label className="block grow">{t("The folder's full path")}
                  <input value={folder} onChange={(e) => setFolder(e.target.value)} required />
                </label>
                <BrowseButton kind="folder" initial={folder} onPick={([p]) => setFolder(p)} />
              </div>
              <label className="check"><input type="checkbox" checked={recursive} onChange={(e) => setRecursive(e.target.checked)} /> {t("Its subfolders too")}</label>
            </>
          ) : (
            <div className="path-row">
              <label className="block grow">{t("The files' full paths, one a line")}
                <textarea value={files} onChange={(e) => setFiles(e.target.value)} rows={4} required />
              </label>
              <BrowseButton kind="files" initial={fileLines[fileLines.length - 1]} onPick={addFiles} />
            </div>
          )}
        </fieldset>
      ) : null}
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

/** A package's page: the processes whose case may read it (`jav/app/intake.py` `package_offers`), each started with one
 *  click; the cases already reading it are linked. */
export function PackageIntake({ offers }: { offers: PackageOffer[] }) {
  return <>{offers.map((o) => <PackageOfferCard key={o.pack} offer={o} />)}</>;
}

function PackageOfferCard({ offer: o }: { offer: PackageOffer }) {
  useLocale();
  const { busy, error, run } = useAction();
  const title = t(o.title);
  const start = () => run(() => api.startCase({ pack: o.pack, name: o.name, sources: o.sources }),
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
