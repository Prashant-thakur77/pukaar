import { useEffect, useState } from 'react';
import { api } from '../api';
import type { StaffGauge } from '../types';

/** A village's active staff gauges, fetched once per village and shared across components. */
const cache = new Map<string, Promise<StaffGauge[]>>();

function load(villageId: string): Promise<StaffGauge[]> {
  let p = cache.get(villageId);
  if (!p) {
    p = api.staffGauges(villageId);
    cache.set(villageId, p);
    p.catch(() => cache.delete(villageId));
  }
  return p;
}

export function forgetStaffGauges(villageId: string) {
  cache.delete(villageId);
}

export function useStaffGauges(villageId: string | null | undefined): { gauges: StaffGauge[] | null } {
  const [state, setState] = useState<{ id: string; gauges: StaffGauge[] } | null>(null);
  useEffect(() => {
    if (!villageId) return;
    let alive = true;
    load(villageId)
      .then((g) => alive && setState({ id: villageId, gauges: g }))
      .catch(() => alive && setState({ id: villageId, gauges: [] }));
    return () => {
      alive = false;
    };
  }, [villageId]);
  return { gauges: state && villageId && state.id === villageId ? state.gauges : null };
}
