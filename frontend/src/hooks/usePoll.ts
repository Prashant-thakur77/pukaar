import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api';
import { useLiveEvents, type LiveEvent } from '../lib/live';

export interface PollState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  refresh: () => Promise<void>;
  updatedAt: number | null;
  /** True while live push is up for every channel this poll listens to. */
  live: boolean;
}

export interface PollOptions {
  /** AppSync Events channels whose events trigger an immediate refetch. */
  live?: string[];
  /** Only events that pass refetch (for example, this village's events only). */
  match?: (e: LiveEvent) => boolean;
  /** Fallback polling interval while live push is healthy. Default 60 s. */
  liveIntervalMs?: number;
}

const NO_CHANNELS: string[] = [];
const DEBOUNCE_MS = 250; // one approval sends a few events at once; refetch once

/**
 * Fetch once, then every `intervalMs` while the tab is visible. Pauses when
 * hidden and refreshes on return. intervalMs = 0 disables polling.
 *
 * With `opts.live`, an event on any of those channels refetches at once, and the
 * interval relaxes to `liveIntervalMs` while the socket is up (polling stays as the
 * fallback for a lost event or a dropped socket).
 */
export function usePoll<T>(fetcher: () => Promise<T>, deps: unknown[], intervalMs = 15000, opts: PollOptions = {}): PollState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const fetcherRef = useRef(fetcher);
  const matchRef = useRef(opts.match);
  const alive = useRef(true);
  const debounce = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastFetch = useRef(0);

  useEffect(() => {
    fetcherRef.current = fetcher;
    matchRef.current = opts.match;
  });

  const refresh = useCallback(async () => {
    try {
      const v = await fetcherRef.current();
      if (!alive.current) return;
      lastFetch.current = Date.now();
      setData(v);
      setError(null);
      setUpdatedAt(lastFetch.current);
    } catch (err) {
      if (!alive.current) return;
      setError(err instanceof ApiError ? err : new ApiError(0, null));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  const { live } = useLiveEvents(opts.live ?? NO_CHANNELS, (e) => {
    if (matchRef.current && !matchRef.current(e)) return;
    if (debounce.current !== null) clearTimeout(debounce.current);
    debounce.current = setTimeout(() => {
      debounce.current = null;
      void refresh();
    }, DEBOUNCE_MS);
  });
  useEffect(
    () => () => {
      if (debounce.current !== null) clearTimeout(debounce.current);
    },
    [],
  );
  const every = intervalMs && live ? Math.max(intervalMs, opts.liveIntervalMs ?? 60000) : intervalMs;

  // Fetch whenever the inputs change.
  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => {
      alive.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, refresh]);

  // Push came (back) up: catch up on anything missed while it was down, unless just fetched.
  useEffect(() => {
    if (live && Date.now() - lastFetch.current > 5000) void refresh();
  }, [live, refresh]);

  // Poll while visible; a change of interval (push up or down) only re-arms the timer.
  useEffect(() => {
    if (!every) return;
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer === null) timer = setInterval(() => void refresh(), every);
    };
    const stop = () => {
      if (timer !== null) clearInterval(timer);
      timer = null;
    };
    const onVis = () => {
      if (document.visibilityState === 'visible') {
        void refresh();
        start();
      } else stop();
    };
    if (document.visibilityState === 'visible') start();
    document.addEventListener('visibilitychange', onVis);
    return () => {
      stop();
      document.removeEventListener('visibilitychange', onVis);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, every, refresh]);

  return { data, error, loading, refresh, updatedAt, live };
}
