import { useCallback, useEffect, useRef, useState } from "react";
import { ACTOR_EVENT, api, ApiError, getActor, type DsPage, type DsQuery, type DsScope } from "./api";

export interface Loaded<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/** A keyed load whose data an action's answer can stand in for. */
export interface Replaceable<T> extends Loaded<T> {
  /** 261 (Q-rogzites-409): takes data the service already sent (an action's answer) as the key's current data; a load
   *  that started before it does not overwrite it when it ends. */
  replace: (data: T) => void;
}

/** Data loading bound to a key. On a key change the previous request's result is discarded, so a slow old response
 *  cannot overwrite the data of the newly selected package (the V4 lesson „kiválasztott csomag identitása” (identity of
 *  the selected package)). */
export function useLoad<T>(key: string | null, fn: () => Promise<T>, pollMs?: number): Replaceable<T> {
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
  // when the service is slow). 153 (review): the mark names the pending request, so a superseded one ending later does
  // not clear it
  const inFlight = useRef(0);
  const requests = useRef(0);
  // 261: the last request started before the data was replaced (its answer, read earlier, would be older)
  const replacedAt = useRef(0);

  useEffect(() => {
    if (key === null) return;
    let alive = true;
    if (loadedKey.current !== key) {
      setData(null); // another package: the old data must not stay on screen
      setError(null);
      gone.current = false;
    }
    setLoading(true);
    const my = ++requests.current;
    inFlight.current = my;
    fnRef.current()
      .then((d) => {
        if (!alive || my <= replacedAt.current) return;
        loadedKey.current = key;
        gone.current = false;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (!alive || my <= replacedAt.current) return;
        loadedKey.current = key;
        const err = e instanceof ApiError ? e : new ApiError(0, "error", String(e));
        gone.current = err.status >= 400 && err.status < 500;
        setError(err);
      })
      .finally(() => {
        if (inFlight.current === my) inFlight.current = 0;
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
  const replace = useCallback((d: T) => {
    replacedAt.current = requests.current;
    loadedKey.current = key;
    gone.current = false;
    setData(d);
    setError(null);
  }, [key]);
  // 231 (U1): under a key not loaded yet there is no data: the render before the new key's effect would otherwise show
  // the old key's data under the new key (a case page asked for the reconciliation of a mailbox case)
  const current = loadedKey.current === key;
  return { data: current ? data : null, error: current ? error : null, loading: loading || (!current && key !== null), reload, replace };
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

/** 153: how soon rows marked `refreshing` are asked for again. */
export const REFRESHING_RETRY_MS = 2000;

/** Dataset page (056 U1). While paging, sorting and filtering, the previous page stays visible until the new one
 *  arrives; on a switch to another dataset or scope, however, it disappears at once (another run's data must not stay
 *  on screen). An old response that arrives later does not overwrite the new one. 153 (review B7): the automatic
 *  refresh waits while a request is pending, on a hidden tab and after a 4xx, as `useLoad` does; before, a query slower
 *  than the refresh was superseded by the next one every time, so the table never filled and the requests piled up. */
export function useDataset(name: string | null, scope: DsScope, query: DsQuery, pollMs?: number): Loaded<DsPage> {
  const [data, setData] = useState<DsPage | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);
  const ident = name === null ? null : JSON.stringify([name, scope]);
  const key = ident === null ? null : JSON.stringify([ident, query]);
  const shownIdent = useRef<string | null>(null);
  const seq = useRef(0);
  const pending = useRef(0); // the request being waited for (0: none)
  const gone = useRef(false); // the last answer was a 4xx: only a change or a manual reload asks again

  useEffect(() => {
    if (key === null || name === null) return;
    const my = ++seq.current;
    pending.current = my;
    if (shownIdent.current !== ident) {
      setData(null);
      setError(null);
    }
    setLoading(true);
    api.datasetQuery(name, scope, query)
      .then((d) => {
        if (my !== seq.current) return;
        shownIdent.current = ident;
        gone.current = false;
        setData(d);
        setError(null);
      })
      .catch((e: unknown) => {
        if (my !== seq.current) return;
        const err = e instanceof ApiError ? e : new ApiError(0, "error", String(e));
        gone.current = err.status >= 400 && err.status < 500;
        setError(err);
      })
      .finally(() => {
        if (pending.current === my) pending.current = 0;
        if (my === seq.current) setLoading(false);
      });
  }, [key, tick]); // eslint-disable-line react-hooks/exhaustive-deps

  const refresh = useCallback(() => {
    if (!gone.current && !pending.current && !document.hidden) setTick((n) => n + 1);
  }, []);

  useEffect(() => {
    if (!pollMs || key === null) return;
    const t = window.setInterval(refresh, pollMs);
    return () => window.clearInterval(t);
  }, [pollMs, key, refresh]);

  // 153: rows served while newer ones are being built are asked for again soon, not only at the next poll
  const refreshing = Boolean(data?.refreshing);
  useEffect(() => {
    if (!refreshing || key === null) return;
    const t = window.setTimeout(refresh, REFRESHING_RETRY_MS);
    return () => window.clearTimeout(t);
  }, [refreshing, data, key, refresh]);

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

/** A failed request in words: the service's own message, or the error's. */
export const errorText = (e: unknown): string => (e instanceof ApiError ? e.message : String(e));

/** 195 (plan G-tidy R6; DECISIONS 195): the action behind a page's buttons - one at a time, the busy state that
 *  disables them, then an error or a notice of what was done. The logic packs' pages (the reconciliation, the routing,
 *  the quote) each wrote this by hand; a page keeps its own small wrapper for what follows a success (`then`) and its
 *  own words for a failure (`failed`, e.g. a conflict that reloads the page). `run` answers whether the action went
 *  through; a second action while one is running is not started. */
export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  async function run<T>(fn: () => Promise<T>, opts: { then?: (result: T) => void; done?: string; failed?: (e: unknown) => string } = {}): Promise<boolean> {
    if (busy) return false;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await fn();
      opts.then?.(result);
      if (opts.done) setNotice(opts.done);
      return true;
    } catch (e) {
      setError(opts.failed ? opts.failed(e) : errorText(e));
      return false;
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, notice, run, setError, setNotice };
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
