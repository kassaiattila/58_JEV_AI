import { useCallback, useEffect, useRef, useState } from "react";
import { ACTOR_EVENT, api, ApiError, getActor, type DsPage, type DsQuery, type DsScope } from "./api";

export interface Loaded<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** Data loading bound to a key. On a key change the previous request's result is discarded, so a slow old response
 *  cannot overwrite the data of the newly selected package (the V4 lesson „kiválasztott csomag identitása” (identity of
 *  the selected package)). */
export function useLoad<T>(key: string | null, fn: () => Promise<T>, pollMs?: number): Loaded<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const loadedKey = useRef<string | null>(null);
  // 063: after a not-found or invalid request (4xx), the automatic refresh does not repeat the request; a manual
  // refresh does
  const gone = useRef(false);
  // 066 Á36: while a request is pending and on a hidden tab, the automatic refresh is skipped (requests do not pile up
  // when the service is slow)
  const inFlight = useRef(false);

  useEffect(() => {
    if (key === null) return;
    let alive = true;
    if (loadedKey.current !== key) {
      setData(null); // another package: the old data must not stay on screen
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

/** 061: the current value of „Ki dolgozik?” (Who is working?); it updates on a change (from any view). */
export function useActor(): string {
  const [actor, setActorState] = useState(getActor);
  useEvent(ACTOR_EVENT, () => setActorState(getActor()));
  return actor;
}

/** Subscription to a window-level event (e.g. a change in the name list). */
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

/** Dataset page (056 U1). While paging, sorting and filtering, the previous page stays visible until the new one
 *  arrives; on a switch to another dataset or scope, however, it disappears at once (another run's data must not stay
 *  on screen). An old response that arrives later does not overwrite the new one. */
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

/** Debounced value (search while typing: not every keystroke sends a request). */
export function useDebounced<T>(value: T, ms = 250): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

/** The statuses of an active (queued or running) run. */
export const ACTIVE_RUN = new Set(["queued", "running"]);

/** 066 Á24: a run's view that refreshes by itself while the run is active (3 s) and stops once it has closed. Until now
 *  the Result section and the approval box did not refresh even at the end of the run; the run details view used this
 *  same pattern. */
export function useRunView(runId: string | null) {
  const [poll, setPoll] = useState(true);
  const view = useLoad(runId ? `run:${runId}` : null, () => api.run(runId!), poll ? 3000 : undefined);
  const status = view.data?.run.status;
  useEffect(() => {
    if (status) setPoll(ACTIVE_RUN.has(status));
  }, [status]);
  return view;
}
