import { CircleCheck, Eye, Siren, TriangleAlert, type LucideIcon } from 'lucide-react';
import { LEVELS, type Level } from '../types';

export const LEVEL_ICON: Record<Level, LucideIcon> = {
  normal: CircleCheck,
  watch: Eye,
  warning: TriangleAlert,
  critical: Siren,
};

export const levelRank = (l: Level | string | null | undefined): number => {
  const i = LEVELS.indexOf(l as Level);
  return i < 0 ? 0 : i;
};

export const isLevel = (v: unknown): v is Level => typeof v === 'string' && (LEVELS as string[]).includes(v);

/** Raw SVG for map markers (kept in sync with LEVEL_ICON glyphs). */
export const LEVEL_SVG: Record<Level, string> = {
  normal: '<circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/>',
  watch: '<path d="M2.06 12.35a1 1 0 0 1 0-.7 10.75 10.75 0 0 1 19.88 0 1 1 0 0 1 0 .7 10.75 10.75 0 0 1-19.88 0"/><circle cx="12" cy="12" r="3"/>',
  warning: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  critical: '<path d="M7 18v-6a5 5 0 1 1 10 0v6"/><path d="M5 21a1 1 0 0 0 1-1v-1a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1a1 1 0 0 0 1 1z"/><path d="M21 12h1"/><path d="M18.5 4.5 18 5"/><path d="M2 12h1"/><path d="M12 2v1"/><path d="m4.929 4.929.707.707"/><path d="M12 12v6"/>',
};
