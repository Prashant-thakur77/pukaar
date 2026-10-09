import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError } from '../api';

export interface PollState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  refresh: () => Promise<void>;
  updatedAt: number | null;
}

/**
 * Fetch once, then every `intervalMs` while the tab is visible. Pauses when
 * hidden and refreshes on return. intervalMs = 0 disables polling.
 */
export function usePoll<T>(fetcher: () => Promise<T>, deps: unknown[], intervalMs = 15000): PollState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [updatedAt, setUpdatedAt] = useState<number | null>(null);
  const fetcherRef = useRef(fetcher);
  const alive = useRef(true);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const refresh = useCallback(async () => {
    try {
      const v = await fetcherRef.current();
      if (!alive.current) return;
      setData(v);
      setError(null);
      setUpdatedAt(Date.now());
    } catch (err) {
      if (!alive.current) return;
      setError(err instanceof ApiError ? err : new ApiError(0, null));
    } finally {
      if (alive.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void refresh();
    if (!intervalMs) return () => {
      alive.current = false;
    };
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer === null) timer = setInterval(() => void refresh(), intervalMs);
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
      alive.current = false;
      stop();
      document.removeEventListener('visibilitychange', onVis);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, intervalMs, refresh]);

  return { data, error, loading, refresh, updatedAt };
}
