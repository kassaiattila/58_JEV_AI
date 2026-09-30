import { useCallback, useEffect, useRef, useState } from "react";
import { ACTOR_EVENT, api, ApiError, getActor, type DsPage, type DsQuery, type DsScope } from "./api";

export interface Loaded<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** Adatbetöltés egy kulcshoz kötve. Kulcsváltáskor az előző kérés eredményét eldobjuk, így egy lassú régi válasz nem
 *  írhatja felül az újonnan kiválasztott csomag adatát (a V4 „kiválasztott csomag identitása” tapasztalata). */
export function useLoad<T>(key: string | null, fn: () => Promise<T>, pollMs?: number): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const loadedKey = useRef<string | null>(null);
  // 063: „nincs ilyen” vagy érvénytelen kérés (4xx) után az automatikus frissítés nem ismétli a kérést; a kézi igen
  const gone = useRef(false);
  // 066 Á36: függő kérés alatt és rejtett lapon az automatikus frissítés kimarad (lassú szolgáltatásnál nem torlódik)
  const inFlight = useRef(false);

  useEffect(() => {
    if (key === null) return;
    let alive = true;
    if (loadedKey.current !== key) {
      setData(null); // másik csomag: a régi adat nem maradhat a képernyőn
      setError(null);
      gone.current = false;
    }
    setLoading(true);
    inFlight.current = true;
    fnRef.current()
      .then((d) => {
        if (!alive) return;
        loadedKey.current = key;
        gone.current = false;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        loadedKey.current = key;
        const err = e instanceof ApiError ? e : new ApiError(0, "error", String(e));
        gone.current = err.status >= 400 && err.status < 500;
        setError(err);
      })
      .finally(() => {
        inFlight.current = false;
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [key, tick]);

  useEffect(() => {
    if (!pollMs || key === null) return;
    const t = window.setInterval(() => {
      if (!gone.current && !inFlight.current && !document.hidden) setTick((n) => n + 1);
    }, pollMs);
    return () => window.clearInterval(t);
  }, [pollMs, key]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading, reload };
}

/** 061: a „Ki dolgozik?” mostani értéke; változáskor (bármelyik nézetből) frissül. */
export function useActor(): string {
  const [actor, setActorState] = useState(getActor);
  useEvent(ACTOR_EVENT, () => setActorState(getActor()));
  return actor;
}

/** Feliratkozás egy ablak-szintű eseményre (pl. a névlista változása). */
export function useEvent(name: string, fn: () => void): void {
  const ref = useRef(fn);
  ref.current = fn;
  useEffect(() => {
    const h = () => ref.current();
    window.addEventListener(name, h);
    return () => window.removeEventListener(name, h);
  }, [name]);
}

export function useHash(): string {
  const [hash, setHash] = useState(() => window.location.hash);
  useEffect(() => {
    const on = () => setHash(window.location.hash);
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash;
}

/** Adatkészlet-lap (056 U1). Lapozás, rendezés és szűrés közben az előző lap látszik, amíg az új megjön; más adatkészletre
 *  vagy hatókörre váltva viszont azonnal eltűnik (nem maradhat másik futás adata a képernyőn). A később érkező régi
 *  válasz nem írja felül az újat. */
export function useDataset(name: string | null, scope: DsScope, query: DsQuery, pollMs?: number): Loaded<DsPage> {
  const [data, setData] = useState<DsPage | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const ident = name === null ? null : JSON.stringify([name, scope]);
  const key = ident === null ? null : JSON.stringify([ident, query]);
  const shownIdent = useRef<string | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    if (key === null || name === null) return;
    const my = ++seq.current;
    if (shownIdent.current !== ident) {
      setData(null);
      setError(null);
    }
    setLoading(true);
    api.datasetQuery(name, scope, query)
      .then((d) => {
        if (my !== seq.current) return;
        shownIdent.current = ident;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (my !== seq.current) return;
        setError(e instanceof ApiError ? e : new ApiError(0, "error", String(e)));
      })
      .finally(() => my === seq.current && setLoading(false));
  }, [key, tick]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!pollMs || key === null) return;
    const t = window.setInterval(() => setTick((n) => n + 1), pollMs);
    return () => window.clearInterval(t);
  }, [pollMs, key]);

  const reload = useCallback(() => setTick((n) => n + 1), []);
  return { data, error, loading, reload };
}

/** Késleltetett érték (gépelés közbeni keresés: nem minden billentyűre megy kérés). */
export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** Aktív (sorban álló vagy futó) futás állapotai. */
export const ACTIVE_RUN = new Set(["queued", "running"]);

/** 066 Á24: egy futás nézete, amely aktív futás alatt magától frissül (3 s), lezárás után leáll. Az Eredmény szakasz és a
 *  jóváhagyó doboz eddig a futás végén sem frissült; a futás-részletek nézete ugyanezt a mintát használta. */
export function useRunView(runId: string | null) {
  const [poll, setPoll] = useState(true);
  const view = useLoad(runId ? `run:${runId}` : null, () => api.run(runId!), poll ? 3000 : undefined);
  const status = view.data?.run.status;
  useEffect(() => {
    if (status) setPoll(ACTIVE_RUN.has(status));
  }, [status]);
  return view;
}
