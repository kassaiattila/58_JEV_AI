// Users (057, 061): the choices of „Ki dolgozik?” (Who is working?). If the list is not empty, changes can only be made
// under a name on the list; the name is the author of a correction, an approval or a run start, and the work package
// owner is also chosen from here. Kept only in the local store. 061: adding and deleting are saved at once (before,
// a separate „Mentés” (Save) was needed, and it got skipped). 264 (plan E, F6; the owner's decision of 2026-10-31: the
// small lists the one list too): the names are the one list (`settings_users`), "New user" the title row's main action
// with a page of its own, a name its own page with when it was added and its removal.
import { useState } from "react";
import { api, ApiError, USERS_EVENT } from "../../api";
import { ConfirmButton } from "../../components/ConfirmButton";
import { DataTable } from "../../components/DataTable";
import { FormActions } from "../../components/FormActions";
import { ItemSteps } from "../../components/ItemSteps";
import { PageActions } from "../../components/PageActions";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";
import { when } from "../../labels";
import { go, settingsHash } from "../../route";
import { settingsChanged, useSettingsTitle } from "./settingsTree";

// 066 Á25: the same rule as the local service's (jav/app/app_settings.py ACTOR_RE): the name must also be usable in the
// author header, otherwise nothing could be done under the added name.
export const ACTOR_NAME = /^[\p{L}\p{N}_.@ -]{1,64}$/u;

const LIST = "settings_users";
const NEW = "new";

export function UsersPanel({ item }: { item?: string }) {
  useLocale();
  if (item === NEW) return <NewUser />;
  if (item) return <UserPage name={item} />;
  return (
    <>
      <PageActions><a className="button primary" href={settingsHash("users", NEW)}>{t("New user")}</a></PageActions>
      <p className="muted small">{t("The header's “Who is working?” picker offers names from this list; when the list is not empty, changes can only be made with a name on the list. The name is recorded with corrections, approvals and runs, and document batch owners are chosen from here as well.")}</p>
      <DataTable dataset={LIST} label={t("Users")} storageId={LIST} persist={LIST}
        emptyText={t("No names in the list yet; until then any name can be typed in the header.")} />
    </>
  );
}

/** Saves the whole list (the service keeps when a staying name was added) and tells the header and the owner picker. */
function useSave() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function save(next: string[]): Promise<boolean> {
    setBusy(true);
    setError(null);
    try {
      await api.saveUsers(next);
      window.dispatchEvent(new Event(USERS_EVENT)); // the header and the owner picker refresh
      settingsChanged();
      return true;
    } catch (e) {
      setError((e as ApiError).message);
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, setError, save };
}

/** A new name's page: the name (by the author rule) with Cancel and Add; saved, it opens the name's page. */
function NewUser() {
  useLocale();
  useSettingsTitle(t("New user"));
  const data = useLoad("users", api.users);
  const [add, setAdd] = useState("");
  const { busy, error, setError, save } = useSave();
  const submit = () => {
    const name = add.trim();
    if (!name || !data.data) return;
    if (!ACTOR_NAME.test(name)) {
      setError(t("A name may contain only letters, digits, spaces, dots, @ and hyphens (at most 64 characters)."));
      return;
    }
    void save([...data.data.users, name]).then((ok) => { if (ok) go({ view: "settings", section: "users", item: name }); });
  };
  return (
    <form className="sheet" aria-label={t("New user")} onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <label className="block">{t("New name")}<input value={add} maxLength={64} onChange={(e) => setAdd(e.target.value)} /></label>
      {error ? <p className="notice error" role="alert">{error}</p> : null}
      <FormActions busy={busy} onCancel={() => go({ view: "settings", section: "users" })}>
        <button type="submit" className={add.trim() ? "primary" : "secondary"} disabled={!add.trim() || busy || !data.data}>{t("Add entry")}</button>
      </FormActions>
    </form>
  );
}

/** A name's page: when it was added, and its removal from the list (it asks first). */
function UserPage({ name }: { name: string }) {
  useLocale();
  useSettingsTitle(name);
  const data = useLoad("users", api.users);
  const added = useLoad(`settings-user:${name}`, () => api.datasetQuery(LIST, {}, { keys: [name], limit: 1 }));
  const { busy, error, save } = useSave();
  if (data.error) return <p className="notice error" role="alert">{data.error.message}</p>;
  if (!data.data) return <p className="muted">{t("Loading…")}</p>;
  if (!data.data.users.includes(name)) return <p className="notice warn">{t("It is not on the list (any more).")}</p>;
  const at = added.data?.rows[0]?.added;
  const remove = () => void save(data.data!.users.filter((x) => x !== name)).then((ok) => { if (ok) go({ view: "settings", section: "users" }); });
  return (
    <>
      <PageActions><ItemSteps list={LIST} /></PageActions>
      <section className="sheet" aria-label={name}>
        <dl className="kv">
          <dt>{t("Name")}</dt><dd>{name}</dd>
          <dt>{t("Added")}</dt><dd>{at ? when(String(at)) : "–"}</dd>
        </dl>
        <p className="muted small">{t("The name stays on what it did before (corrections, approvals, runs); it is only no longer offered.")}</p>
        {error ? <p className="notice error" role="alert">{error}</p> : null}
        <FormActions start={<ConfirmButton className="quiet" danger disabled={busy} ariaLabel={t("Remove {{name}} from the list", { name })}
          question={t("Remove {{name}} from the list?", { name })} onConfirm={remove}>{t("Remove from the list")}</ConfirmButton>} />
      </section>
    </>
  );
}
