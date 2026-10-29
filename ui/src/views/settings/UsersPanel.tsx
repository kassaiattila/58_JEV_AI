// Users (057, 061): the choices of „Ki dolgozik?” (Who is working?). If the list is not empty, changes can only be made
// under a name on the list; the name is the author of a correction, an approval or a run start, and the work package
// owner is also chosen from here. Kept only in the local store. 061: adding and deleting are saved at once (before,
// a separate „Mentés” (Save) was needed, and it got skipped).
import { useEffect, useState } from "react";
import { api, ApiError, USERS_EVENT } from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";

// 066 Á25: the same rule as the local service's (jav/app/app_settings.py ACTOR_RE): the name must also be usable in the
// author header, otherwise nothing could be done under the added name.
export const ACTOR_NAME = /^[\p{L}\p{N}_.@ -]{1,64}$/u;

export function UsersPanel() {
  useLocale();
  const data = useLoad("users", api.users);
  const [draft, setDraft] = useState<string[]>([]);
  const [add, setAdd] = useState("");
  const [msg, setMsg] = useState<{ error: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (data.data) setDraft(data.data.users); }, [data.data]);

  async function save(next: string[], text: string): Promise<boolean> {
    setBusy(true);
    setMsg(null);
    try {
      const res = await api.saveUsers(next);
      setDraft(res.users);
      setMsg({ error: false, text });
      data.reload();
      window.dispatchEvent(new Event(USERS_EVENT)); // the header and the owner picker refresh
      return true;
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card wide" aria-label={t("Users")}>
      <p className="muted small">{t("The header's “Who is working?” picker offers names from this list; when the list is not empty, changes can only be made with a name on the list. The name is recorded with corrections, approvals and runs, and document batch owners are chosen from here as well.")}</p>
      {data.error ? <p className="notice error">{data.error.message}</p> : null}
      <ul className="plain user-list">
        {draft.map((u) => (
          <li key={u}>
            <span>{u}</span>
            <ConfirmButton className="quiet small-btn" disabled={busy} ariaLabel={t("Remove {{name}} from the list", { name: u })}
              onConfirm={() => void save(draft.filter((x) => x !== u), t("{{name}} removed from the list.", { name: u }))}>{t("Delete")}</ConfirmButton>
          </li>
        ))}
        {data.data && draft.length === 0 ? <li className="muted">{t("No names in the list yet; until then any name can be typed in the header.")}</li> : null}
      </ul>
      <form className="form-row" onSubmit={(e) => {
        e.preventDefault();
        const name = add.trim();
        if (name && !ACTOR_NAME.test(name)) {
          setMsg({ error: true, text: t("A name may contain only letters, digits, spaces, dots, @ and hyphens (at most 64 characters).") });
          return;
        }
        if (name) void save([...draft, name], t("{{name}} added and saved.", { name })).then((ok) => { if (ok) setAdd(""); });
      }}>
        <label className="block">{t("New name")}<input value={add} maxLength={64} onChange={(e) => setAdd(e.target.value)} /></label>
        <button type="submit" className={add.trim() ? "primary" : "secondary"} disabled={!add.trim() || busy}>{t("Add entry")}</button>
      </form>
      {msg ? <p className={msg.error ? "notice error" : "muted small"} role={msg.error ? "alert" : "status"}>{msg.text}</p> : null}
    </section>
  );
}
