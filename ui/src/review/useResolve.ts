// 066 Á23: the to-do's „Rendezve” (Resolved) button. Until now an error was silently lost (try/finally, without a
// catch), and the button could be pressed again while the request was pending. Now only one request goes at a time, an
// error shows a message, and the list is refreshed (after success or error alike), because the cause of the error may
// be that someone else resolved it in the meantime.
import { useRef, useState } from "react";
import { api, ApiError, type Reason } from "../api";
import { t } from "../i18n";

export function useResolve(onDone: () => void) {
  const [pending, setPending] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const busy = useRef(false); // synchronous lock: between two quick clicks React's state has not yet updated

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
