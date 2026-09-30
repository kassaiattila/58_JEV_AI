// Felhasználók (057, 061): a „Ki dolgozik?” választéka. Ha a lista nem üres, módosítani csak a listán szereplő névvel
// lehet; a név a javítás, a jóváhagyás, a futás indítása szerzője, és a csomag felelőse is innen választható. Csak a
// helyi adattárban. 061: a felvétel és a törlés azonnal mentődik (előtte külön „Mentés” kellett, és elmaradt).
import { useEffect, useState } from "react";
import { api, ApiError, USERS_EVENT } from "../../api";
import { useLoad } from "../../hooks";
import { t, useLocale } from "../../i18n";

// 066 Á25: ugyanaz a szabály, mint a szolgáltatásé (jav/app_settings.py ACTOR_RE): a névnek a szerző-fejlécben is
// használhatónak kell lennie, különben a felvett névvel semmit nem lehetne tenni.
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
      window.dispatchEvent(new Event(USERS_EVENT)); // a fejléc és a felelős-választó frissül
      return true;
    } catch (e) {
      setMsg({ error: true, text: (e as ApiError).message });
      return false;
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card wide" aria-label={t("Felhasználók")}>
      <p className="muted small">{t("A fejléc „Ki dolgozik?” választója ebből a listából kínál; ha a lista nem üres, módosítani csak a listán szereplő névvel lehet. A név kerül a javítások, a jóváhagyások és a futások mellé, és a csomag felelőse is innen választható.")}</p>
      {data.error ? <p className="notice error">{data.error.message}</p> : null}
      <ul className="plain user-list">
        {draft.map((u) => (
          <li key={u}>
            <span>{u}</span>
            <button type="button" className="quiet small-btn" disabled={busy} aria-label={t("{{name}} törlése a listából", { name: u })}
              onClick={() => void save(draft.filter((x) => x !== u), t("{{name}} törölve a listából.", { name: u }))}>{t("Törlés")}</button>
          </li>
        ))}
        {data.data && draft.length === 0 ? <li className="muted">{t("Még nincs név a listában; addig a fejlécben szabadon írható.")}</li> : null}
      </ul>
      <form className="form-row" onSubmit={(e) => {
        e.preventDefault();
        const name = add.trim();
        if (name && !ACTOR_NAME.test(name)) {
          setMsg({ error: true, text: t("A név csak betűt, számot, szóközt, pontot, @ jelet és kötőjelet tartalmazhat (legfeljebb 64 karakter).") });
          return;
        }
        if (name) void save([...draft, name], t("{{name}} felvéve és mentve.", { name })).then((ok) => { if (ok) setAdd(""); });
      }}>
        <label className="block">{t("Új név")}<input value={add} maxLength={64} onChange={(e) => setAdd(e.target.value)} /></label>
        <button type="submit" className="primary" disabled={!add.trim() || busy}>{t("Felvétel")}</button>
      </form>
      {msg ? <p className={msg.error ? "notice error" : "muted small"} role={msg.error ? "alert" : "status"}>{msg.text}</p> : null}
    </section>
  );
}
