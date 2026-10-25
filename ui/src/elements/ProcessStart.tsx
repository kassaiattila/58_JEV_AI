// 231 (plan stage C, C1c; DECISIONS 231): starting a process pack's case that reads work packages (its scope part
// `sources`), the same way for every process: from the new work wizard (the packages of the kinds its intake takes, to
// choose) and from such a package's own page (the processes that take it, with the cases already reading it). Until
// C1c the email routing's own form and offer.
import { useState } from "react";
import { api, type PackageOffer } from "../api";
import { Icon } from "../components/Icon";
import { useAction, useLoad } from "../hooks";
import { t, useLocale } from "../i18n";
import { go } from "../route";

/** The wizard's form of a one-step template of a process pack's case: the packages it reads and its name. */
export function ProcessCreate({ pack, onDone }: { pack: string; onDone: (wpId: string) => void }) {
  useLocale();
  const packs = useLoad("processes", api.processes);
  const list = useLoad("workpackages-brief", api.workpackagesBrief);
  const [chosen, setChosen] = useState<string[]>([]);
  const [name, setName] = useState("");
  const { busy, error, run } = useAction();
  const info = packs.data?.processes.find((p) => p.id === pack);
  if (packs.error) return <p className="notice error" role="alert">{packs.error.message}</p>;
  if (!info) return <p className="muted">{t("Loading…")}</p>;
  const title = t(info.title);
  const candidates = (list.data?.workpackages ?? []).filter((w) => (info.package_kinds ?? []).includes(w.source_kind));
  const submit = () => run(() => {
    const names = candidates.filter((w) => chosen.includes(w.id)).map((w) => w.name);
    return api.startCase({ pack, name: (name.trim() || `${title}: ${names.join(", ")}`).slice(0, 200), sources: chosen });
  }, { then: (made) => onDone(made.case_id) });
  return (
    <form className="create rc-stack" aria-label={title} onSubmit={(e) => { e.preventDefault(); if (chosen.length) void submit(); }}>
      {list.error ? <p className="notice error" role="alert">{list.error.message}</p> : null}
      <fieldset className="wizard-choices">
        <legend>{t("The packages the case reads")}</legend>
        {candidates.length ? candidates.map((w) => (
          <label key={w.id} className="check">
            <input type="checkbox" checked={chosen.includes(w.id)}
              onChange={(e) => setChosen((prev) => (e.target.checked ? [...prev, w.id] : prev.filter((x) => x !== w.id)))} /> {w.name}
          </label>
        )) : <p className="muted small">{list.data ? t("No package this process reads yet.") : t("Loading…")}</p>}
      </fieldset>
      <label className="block">{t("Name")} <span className="muted">{t("(optional)")}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} />
      </label>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      <div className="button-row">
        <button type="submit" className="primary" disabled={busy || !chosen.length}>{busy ? t("Creating…") : t("Create")}</button>
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
