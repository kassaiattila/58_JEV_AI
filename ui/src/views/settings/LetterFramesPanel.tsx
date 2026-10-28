// 231 (stage U, U3f; the owner's decision of 2026-10-28: the letter frames are edited now, with versions): the letter
// frames of the shared library (`jav/app/letter_frames.py`). Each kind (the covering letters, the quote's reply letters)
// lists its frames: the text in effect field by field, the processes that use it, and its versions. A person changes
// the text in a form and saves it as a draft; the draft is made active by the rule of who may (the process values'
// rule), and "Back to the system's text" sets the own text aside. A case keeps the text active when it starts.
import { useState } from "react";
import { api, ApiError, type FrameContent, type FrameField, type LetterFrame, type LetterFrameKind, type UsedByMap } from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { UsedBy, useUsedBy } from "../../components/UsedBy";
import { VersionState } from "../../components/VersionState";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";

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

export function LetterFramesPanel() {
  useLocale();
  const data = useLoad("letter-frames", api.letterFrames);
  return (
    <section className="stage-stack" aria-label={t("Letter frames")}>
      <p className="muted small">
        {t("A letter frame is the text of a letter that goes with a printed document: its subject, greeting, paragraphs and closing, with markers such as {{total}} that the system fills in from the document. A changed text is saved as a draft and used once it is made active, by the cases that start after it; a case keeps the text it started with.")}
      </p>
      {data.error ? <p className="notice error" role="alert">{data.error.message}</p> : null}
      {!data.data && !data.error ? <p className="muted">{t("Loading…")}</p> : null}
      {data.data?.kinds.map((k) => <FrameKind key={k.kind} kind={k} onChanged={data.reload} />)}
    </section>
  );
}

function FrameKind({ kind, onChanged }: { kind: LetterFrameKind; onChanged: () => void }) {
  useLocale();
  const used = useUsedBy(kind.kind);
  return (
    <section className="card wide" aria-label={t(kind.title)}>
      <h3>{t(kind.title)}</h3>
      <p className="muted small">{t(kind.what)}</p>
      {kind.frames.map((f) => <Frame key={f.ident} kind={kind} frame={f} used={used} onChanged={onChanged} />)}
    </section>
  );
}

function Frame({ kind, frame, used, onChanged }: { kind: LetterFrameKind; frame: LetterFrame; used: UsedByMap | null; onChanged: () => void }) {
  useLocale();
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
    <div className="template-output-block letter-frame" aria-label={frame.ident}>
      <div className="template-output-head">
        <h4 className="mono">{frame.ident}</h4>
        <span className="muted small">
          {frame.active ? t("its own text: version {{n}}", { n: frame.active }) : t("the system's text")}
        </span>
        {!editing ? <button type="button" className="secondary small-btn" disabled={busy} onClick={() => { setMsg(null); setEditing(true); }}>{t("Change the text")}</button> : null}
      </div>
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
                    <button type="button" className={v.state === "draft" ? "primary small-btn" : "secondary small-btn"} disabled={busy}
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
      <div className="button-row">
        <button type="submit" className="primary" disabled={busy || !changed.length}>{t("Save as a draft")}</button>
        <button type="button" className="quiet" disabled={busy} onClick={onCancel}>{t("Cancel")}</button>
      </div>
    </form>
  );
}
