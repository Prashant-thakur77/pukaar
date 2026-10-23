import { createContext, useContext } from 'react';
import type { PollState } from '../../hooks/usePoll';
import type { Alert, Health, Report, RosterView, Village } from '../../types';

/** What every console section shares, polled once by the layout (ConsoleLayout.tsx). */
export interface ConsoleData {
  username: string;
  role: string;
  officer: boolean;
  /** The public demo accounts (judge, judge_pradhan): they act on replays only. */
  judge: boolean;
  villageIds: string[];
  villages: PollState<Village[]>;
  pending: PollState<Alert[]>;
  alerts: PollState<Alert[]>;
  health: PollState<Health>;
  roster: PollState<RosterView>;
  reports: PollState<Report[]>;
  showDemo: boolean;
  setShowDemo: (on: boolean) => void;
  refreshAlerts: () => void;
  /** The district the officer is looking at ('' for all); the villages, alerts and reports above are filtered to it. */
  district: string;
  districts: string[];
  setDistrict: (d: string) => void;
}

export const ConsoleCtx = createContext<ConsoleData | null>(null);

export function useConsole(): ConsoleData {
  const c = useContext(ConsoleCtx);
  if (!c) throw new Error('useConsole outside the console');
  return c;
}
