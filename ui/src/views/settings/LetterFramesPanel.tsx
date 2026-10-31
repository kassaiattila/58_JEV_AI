// 231 (stage U, U3f; the owner's decision of 2026-10-28: the letter frames are edited now, with versions): the letter
// frames of the shared library (`jav/app/letter_frames.py`). Each kind (the covering letters, the quote's reply letters)
// lists its frames: the text in effect field by field, the processes that use it, and its versions. A person changes
// the text in a form and saves it as a draft; the draft is made active by the rule of who may (the process values'
// rule), and "Back to the system's text" sets the own text aside. A case keeps the text active when it starts. 263 (plan
// E, E1; the owner's decisions of 2026-10-30): the frames are the one list (by kind, language, own or the system's
// text); a frame is a page of its own (its kind and id in the address).
import { useState } from "react";
import { api, ApiError, type FrameContent, type FrameField, type LetterFrame, type LetterFrameKind } from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { FormActions } from "../../components/FormActions";
import { DataTable } from "../../components/DataTable";
import { ItemSteps } from "../../components/ItemSteps";
import { PageActions } from "../../components/PageActions";
import { UsedBy, useUsedBy } from "../../components/UsedBy";
import { VersionState } from "../../components/VersionState";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";
import { settingsChanged, useSettingsTitle } from "./settingsTree";

const LIST = "settings_letter_frames";

type Values = Record<string, string>;

function fieldValue(content: FrameContent, path: string): unknown {
  return path.split(".").reduce<unknown>((node, part) => (node && typeof node === "object" ? (node as Record<string, unknown>)[part] : undefined), content);
}

/** A field as the form edits it: paragraphs as one text, a blank line between two. */
function asText(field: FrameField, content: FrameContent): string {
  const value = fieldValue(content, field.path);
  if (field.form === "paragraphs") return Array.isArray(value) ? value.join("\n\n") : "";
  return typeof value === "string" ? value : "";
}

/** The fields under their groups (a language), in their order; fields without a group stand under none. */
function groups(fields: FrameField[]): [string | null, FrameField[]][] {
  const out = new Map<string | null, FrameField[]>();
  for (const f of fields) out.set(f.group, [...(out.get(f.group) ?? []), f]);
  return [...out.entries()];
}

export function LetterFramesPanel({ item, tab }: { item?: string; tab?: string }) {
  useLocale();
  const data = useLoad("letter-frames", api.letterFrames);
  const kind = item ? data.data?.kinds.find((k) => k.kind === item) : undefined;
  const frame = kind && tab ? kind.frames.find((f) => f.ident === tab) : undefined;
  const subject = frame ? String(fieldValue(frame.content, "subject") ?? "") : "";
  useSettingsTitle(frame ? subject || frame.ident : null);
  if (data.error) return <p className="notice error" role="alert">{data.error.message}</p>;
  if (!data.data) return <p className="muted">{t("Loading…")}</p>;
  if (item) {
    if (!kind || !frame) return <p className="notice warn">{t("It is not among the letter frames (any more).")}</p>;
    return (
      <>
        <PageActions><ItemSteps list={LIST} /></PageActions>
        <p className="muted small">{t(kind.title)} · <span className="mono">{frame.ident}</span> — {t(kind.what)}</p>
        <Frame key={frame.ident} kind={kind} frame={frame} onChanged={() => { data.reload(); settingsChanged(); }} />
      </>
    );
  }
  return (
    <section className="stage-stack" aria-label={t("Letter frames")}>
      <p className="muted small">
        {t("A letter frame is the text of a letter that goes with a printed document: its subject, greeting, paragraphs and closing, with markers such as {{total}} that the system fills in from the document. A changed text is saved as a draft and used once it is made active, by the cases that start after it; a case keeps the text it started with.")}
      </p>
      <DataTable dataset={LIST} label={t("Letter frames")} storageId={LIST} persist={LIST} />
    </section>
  );
}

function Frame({ kind, frame, onChanged }: { kind: LetterFrameKind; frame: LetterFrame; onChanged: () => void }) {
  useLocale();
  const used = useUsedBy(kind.kind);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);

  async function act(fn: () => Promise<unknown>, done: string) {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
      setMsg({ error: false, text: done });
      onChanged();
      return true;
    } catch (e) {
      setMsg({ error: true, text: e instanceof ApiError ? e.message : String(e) });
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sheet letter-frame" aria-label={frame.ident}>
      <p className="small">
        {frame.active ? <VersionState state="active" /> : null}{" "}
        {frame.active ? t("its own text: version {{n}}", { n: frame.active }) : t("the system's text")}
      </p>
      {!editing ? <PageActions><button type="button" className="primary" disabled={busy} onClick={() => { setMsg(null); setEditing(true); }}>{t("Change the text")}</button></PageActions> : null}
      <UsedBy used={used} ident={frame.ident} />
      {editing ? (
        <FrameForm kind={kind} frame={frame} busy={busy} onCancel={() => setEditing(false)}
          onSave={async (values, note) => {
            if (await act(() => api.proposeLetterFrame(kind.kind, frame.ident, values, note), t("Saved as a draft. Make it active to use it."))) setEditing(false);
          }} />
      ) : <FrameText kind={kind} content={frame.content} />}
      {frame.versions.length ? (
        <table className="table compact frame-versions" aria-label={t("Versions")}>
          <thead><tr><th className="num">{t("Version")}</th><th>{t("State")}</th><th>{t("Made by")}</th><th>{t("Note")}</th><th><span className="sr-only">{t("Actions")}</span></th></tr></thead>
          <tbody>
            {frame.versions.map((v) => (
              <tr key={v.version}>
                <td className="num tnum">{t("version {{n}}", { n: v.version })}</td>
                <td><VersionState state={v.state} /></td>
                <td><span>{v.made_by}</span> <span className="muted tnum">{when(v.made_at)}</span></td>
                <td>{v.note ?? "–"}</td>
                <td className="button-row">
                  {v.state === "draft" || v.state === "superseded" ? (
                    <button type="button" className="secondary small-btn" disabled={busy}
                      onClick={() => void act(() => api.activateLetterFrame(kind.kind, frame.ident, v.version), t("Version {{n}} is active: the cases that start from now on use it.", { n: v.version }))}>
                      {t("Make version {{n}} active", { n: v.version })}
                    </button>
                  ) : null}
                  {v.state === "active" ? (
                    <ConfirmButton className="secondary small-btn" disabled={busy}
                      onConfirm={() => void act(() => api.retireLetterFrame(kind.kind, frame.ident), t("The system's text counts again for the cases that start from now on."))}>
                      {t("Back to the system's text")}
                    </ConfirmButton>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {msg ? <p role="status" className={msg.error ? "notice error" : "small ok"}>{msg.text}</p> : null}
    </div>
  );
}

/** The text in effect, field by field under its group (a language). */
function FrameText({ kind, content }: { kind: LetterFrameKind; content: FrameContent }) {
  useLocale();
  return (
    <div className="frame-text">
      {groups(kind.fields).map(([group, fields]) => (
        <div key={group ?? ""} className="frame-group">
          {group ? <h5>{t(group)}</h5> : null}
          <dl>
            {fields.map((f) => (
              <div key={f.path} className="frame-field">
                <dt>{t(f.label)}</dt>
                <dd>{asText(f, content)}</dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  );
}

function FrameForm({ kind, frame, busy, onCancel, onSave }: {
  kind: LetterFrameKind; frame: LetterFrame; busy: boolean; onCancel: () => void;
  onSave: (values: Record<string, string | string[]>, note: string | null) => void;
}) {
  useLocale();
  const start: Values = Object.fromEntries(kind.fields.map((f) => [f.path, asText(f, frame.content)]));
  const [values, setValues] = useState<Values>(start);
  const [note, setNote] = useState("");
  const changed = kind.fields.filter((f) => values[f.path] !== start[f.path]);
  const save = () => onSave(Object.fromEntries(changed.map((f) => [f.path, f.form === "paragraphs"
    ? values[f.path].split(/\n\s*\n/).map((p) => p.trim()).filter(Boolean) : values[f.path]])), note.trim() || null);
  return (
    <form className="frame-form" aria-label={t("Change the text")} onSubmit={(e) => { e.preventDefault(); save(); }}>
      {groups(kind.fields).map(([group, fields]) => (
        <fieldset key={group ?? ""} className="frame-group">
          {group ? <legend>{t(group)}</legend> : null}
          {fields.map((f) => (
            <label key={f.path} className="block">{t(f.label)}
              {f.form === "line" ? (
                <input value={values[f.path]} maxLength={300} autoComplete="off" onChange={(e) => setValues({ ...values, [f.path]: e.target.value })} />
              ) : (
                <textarea value={values[f.path]} rows={f.form === "paragraphs" ? 6 : 3} maxLength={5000}
                  onChange={(e) => setValues({ ...values, [f.path]: e.target.value })} />
              )}
              {f.form === "paragraphs" ? <span className="muted small">{t("A blank line starts a new paragraph.")}</span> : null}
            </label>
          ))}
        </fieldset>
      ))}
      <p className="muted small frame-markers">
        {t("Markers you can use:")} {kind.markers.map((m, i) => <span key={m}>{i ? ", " : ""}<span className="mono">{`{{${m}}}`}</span></span>)}
      </p>
      <label className="block">{t("Note")}
        <input value={note} maxLength={2000} autoComplete="off" onChange={(e) => setNote(e.target.value)} />
      </label>
      <FormActions onCancel={onCancel} busy={busy}>
        <button type="submit" className="primary" disabled={busy || !changed.length}>{t("Save as a draft")}</button>
      </FormActions>
    </form>
  );
}
