// 066 Á23: a teendő „Rendezve” gombja. Eddig a hiba csendben elveszett (try/finally, catch nélkül), és a függő kérés alatt
// a gomb újra megnyomható volt. Most egyszerre egy kérés megy, hiba esetén üzenet látszik, és a lista (siker vagy hiba
// után is) frissül, mert a hiba oka lehet, hogy közben más rendezte.
import { useRef, useState } from "react";
import { api, ApiError, type Reason } from "../api";
import { t } from "../i18n";

export function useResolve(onDone: () => void) {
  const [pending, setPending] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false); // szinkron zár: két gyors kattintás közt a React állapota még nem frissült

  async function resolve(r: Reason): Promise<void> {
    if (busy.current) return;
    busy.current = true;
    setPending(r.id);
    setError(null);
    try {
      await api.resolveReason(r.id);
    } catch (e) {
      setError(t("Nem sikerült rendezni: {{reason}}", { reason: e instanceof ApiError ? e.message : String(e) }));
    } finally {
      busy.current = false;
      setPending(null);
      onDone();
    }
  }

  return { resolve, pending, error };
}
