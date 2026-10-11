// 146 (backlog D-bank-files; the owner's request of 2026-10-11): which bank files the system reads, and how. The
// catalogue comes from the local service (`configs/bank_files.json` with the readers' own configuration, GET
// /bank-files), so it follows the readers: per kind of file its bank, files, reader (code or AI), the statement's and
// each line's facts, what it does not read, its checks and notes; then the files no reader knows. Its texts are English
// source strings translated here; the facts' names are the field labels. Shown in Settings › Processing and, folded,
// on the new statement package's form.
import { useState } from "react";
import { api, type BankFile, type BankFilesCatalogue } from "../api";
import { useLoad } from "../hooks";
import { t, useLocale } from "../i18n";

function names(keys: string[], labels: Record<string, string>): string {
  return keys.length ? keys.map((k) => t(labels[k] ?? k)).join(", ") : "–";
}

function BankFileCard({ file, cat }: { file: BankFile; cat: BankFilesCatalogue }) {
  useLocale();
  const title = `${t(file.bank ?? file.id)}: ${t(file.statement ?? file.id)}`;
  return (
    <section className="card wide recipe-doc" aria-label={title}>
      <div className="card-head">
        <h3>{title}</h3>
        <span className={file.read_by === "code" ? "ok small" : "warn-text small"}>{t(cat.read_by[file.read_by])}</span>
      </div>
      <dl className="recipe-kv">
        {file.formats.length ? (
          <>
            <dt>{t("Files")}</dt>
            <dd><ul className="tight">{file.formats.map((f) => <li key={f}>{t(f)}</li>)}</ul></dd>
          </>
        ) : null}
        <dt>{t("File types")}</dt><dd className="mono">{file.suffixes.join(" ")}</dd>
        <dt>{t("The statement")}</dt><dd>{names(file.header, cat.labels)}</dd>
        <dt>{t("Each line")}</dt><dd>{names(file.reads, cat.labels)}</dd>
        <dt>{t("Not read")}</dt><dd>{names(file.not_read, cat.labels)}</dd>
        <dt>{t("Checks")}</dt>
        <dd>{file.checks.length ? <ul className="tight">{file.checks.map((c) => <li key={c}>{t(cat.checks[c] ?? c)}</li>)}</ul> : "–"}</dd>
        <dt>{t("Reader")}</dt><dd className="mono small">{file.reader.profile ?? file.reader.type} · {file.version}</dd>
      </dl>
      {file.notes.length ? <ul className="tight small">{file.notes.map((n) => <li key={n}>{t(n)}</li>)}</ul> : null}
      {file.described ? null : <p className="small warn-text">{t("Not described yet: only its configuration is known.")}</p>}
    </section>
  );
}

/** The whole catalogue: the introduction, a card per kind of file, and the files no reader knows. */
export function BankFilesPanel() {
  useLocale();
  const loaded = useLoad("bank-files", api.bankFiles);
  if (loaded.error) return <p className="notice error" role="alert">{loaded.error.message}</p>;
  if (!loaded.data) return <p className="muted small">{t("Loading…")}</p>;
  const cat = loaded.data;
  return (
    <div className="rc-stack" aria-label={t("Bank files the system reads")}>
      <p className="page-summary">{t(cat.intro)}</p>
      {cat.files.map((f) => <BankFileCard key={f.id} file={f} cat={cat} />)}
      <section className="card wide recipe-doc" aria-label={t("Files no reader knows")}>
        <h3>{t("Files no reader knows")}</h3>
        <ul className="tight">{cat.not_read.map((n) => <li key={n}>{t(n)}</li>)}</ul>
      </section>
    </div>
  );
}

/** Folded under a question; the catalogue is fetched only when it is opened. */
export function BankFilesInfo() {
  useLocale();
  const [open, setOpen] = useState(false);
  return (
    <details onToggle={(e) => setOpen((e.currentTarget as HTMLDetailsElement).open)}>
      <summary className="small">{t("Which bank files can the system read?")}</summary>
      {open ? <BankFilesPanel /> : null}
    </details>
  );
}
