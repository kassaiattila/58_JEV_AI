// 231 (stage D0, D0-g; the reassessment of 2026-10-26, F15, P12): what an editor says about its saves, and a save
// refused because someone else saved meanwhile, with my changes beside theirs (`editing.ts`).
import type { ReactNode } from "react";
import { t, useLocale } from "../i18n";
import { when } from "../labels";
import { ConfirmButton } from "./ConfirmButton";
import type { Change, SaveState } from "./editing";

/** The save line: no change, changed, saving, saved (when), not saved (a conflict), or not known. */
export function SaveLine({ state, savedAt, idle }: { state: SaveState; savedAt: string | null; idle: string }) {
  useLocale();
  const text: Record<SaveState, string> = {
    clean: idle,
    changed: t("Changes not saved yet"),
    saving: t("Saving…"),
    saved: savedAt ? t("Saved {{when}}", { when: when(savedAt) }) : idle,
    conflict: t("Not saved: someone else saved it meanwhile"),
    unknown: t("Whether it was saved is not known"),
  };
  return <span className="muted small" role="status" data-state={state}>{text[state]}</span>;
}

/** The connection broke while saving: whether the changes reached the service is not known; they are kept here. */
export function SaveUnknown({ busy, onAgain }: { busy: boolean; onAgain: () => void }) {
  useLocale();
  return (
    <div className="notice warn small" role="alert">
      <p>{t("The connection broke while saving: whether your changes reached the service is not known. They are kept on this page until you save them or leave it.")}</p>
      <button type="button" className="secondary small-btn" disabled={busy} onClick={onAgain}>{t("Save again")}</button>
    </div>
  );
}

/** A save refused because someone else saved meanwhile: each of my changes beside the value saved now (marked where
 *  they changed it too); keeping mine applies only my changes over theirs, taking theirs drops mine (asks once more). */
export function SaveConflict({ changes, label, value, busy, onKeepMine, onTakeTheirs }: {
  /** null while the version saved now is being read */
  changes: Change[] | null;
  label: (path: string[]) => string;
  value: (path: string[], v: unknown) => ReactNode;
  busy: boolean;
  onKeepMine: () => void;
  onTakeTheirs: () => void;
}) {
  useLocale();
  return (
    <section className="notice warn small save-conflict" role="alert" aria-label={t("Not saved")}>
      <p>{t("Someone else saved this meanwhile, so your changes were not saved. They are kept here: compare them with the version saved now.")}</p>
      {changes === null ? <p className="muted">{t("Loading…")}</p> : (
        <table className="table compact">
          <thead><tr><th>{t("What")}</th><th>{t("Mine")}</th><th>{t("Saved now")}</th></tr></thead>
          <tbody>
            {changes.map((c) => (
              <tr key={JSON.stringify(c.path)}>
                <td>{label(c.path)}{c.gone ? <div className="muted small">{t("they removed it: yours cannot be applied")}</div>
                  : c.both ? <div className="muted small">{t("changed by them too")}</div> : null}</td>
                <td>{value(c.path, c.mine)}</td>
                <td>{value(c.path, c.theirs)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="save-conflict-actions">
        <button type="button" className="primary small-btn" disabled={busy || changes === null} onClick={onKeepMine}>
          {t("Keep my changes")}</button>
        <ConfirmButton className="secondary small-btn" disabled={busy} onConfirm={onTakeTheirs}>{t("Drop mine, keep theirs")}</ConfirmButton>
      </div>
    </section>
  );
}
