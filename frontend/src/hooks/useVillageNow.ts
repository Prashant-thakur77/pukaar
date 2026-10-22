import { useEffect, useMemo, useState } from 'react';
import { api, ApiError } from '../api';
import { nowFromDetail, readCachedNow, writeCachedNow, type VillageNow } from '../lib/villageNow';
import { useNet } from '../store';
import type { VillageDetail } from '../types';

export interface NowState {
  now: VillageNow | null;
  /** Where the answer on screen came from: this phone's last copy, the small answer, or the full detail. */
  source: 'cache' | 'now' | 'detail' | null;
  /** The last request failed for want of a network: what is shown is the phone's copy. */
  offline: boolean;
  /** The village does not exist (the API said 404 for the full detail). */
  missing: boolean;
}

interface Fetched {
  id: string;
  now: VillageNow | null;
  source: 'cache' | 'now' | null;
  offline: boolean;
}

function initial(id: string): Fetched {
  const c = readCachedNow(id);
  return { id, now: c?.now ?? null, source: c ? 'cache' : null, offline: false };
}

/**
 * The village answer, fastest first: the phone's last copy at once, then GET /public/villages/{id}/now (started
 * at boot, api.prefetchRoute), then each poll of the full detail. Every fresh answer is kept on the phone.
 */
export function useVillageNow(id: string, detail: VillageDetail | null, detailError: ApiError | null): NowState {
  const [fetched, setFetched] = useState<Fetched>(() => initial(id));
  const online = useNet((s) => s.online);
  // A new village: start from its own copy (state adjusted during render, not in an effect).
  const base = fetched.id === id ? fetched : initial(id);
  if (fetched.id !== id) setFetched(base);

  useEffect(() => {
    let live = true;
    api
      .villageNow(id)
      .then((now) => {
        if (live) setFetched({ id, now, source: 'now', offline: false });
      })
      .catch((err: unknown) => {
        // No network: keep the phone's copy and say so. A 404 here can be an older API without /now: the
        // full detail decides whether the village exists.
        if (live && err instanceof ApiError && err.isNetwork) setFetched((f) => (f.id === id ? { ...f, offline: true } : f));
      });
    return () => {
      live = false;
    };
  }, [id]);

  // Each poll of the full detail is the newest word on the level; the safe place comes from /now.
  const now = useMemo<VillageNow | null>(() => {
    if (detail && detail.village.id === id) return { ...nowFromDetail(detail), safe_place: base.now?.safe_place ?? null };
    return base.now;
  }, [detail, id, base.now]);
  const source: NowState['source'] = detail && detail.village.id === id ? 'detail' : base.source;

  // Keep every fresh answer on the phone for the next visit and for no signal.
  useEffect(() => {
    if (now && source !== 'cache') writeCachedNow(now);
  }, [now, source]);

  const missing = detailError?.status === 404;
  const offline = Boolean(now) && (!online || Boolean(detailError?.isNetwork) || (source !== 'detail' && base.offline));
  return { now, source, offline, missing };
}
