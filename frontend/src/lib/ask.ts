import type { Level, ToolCall } from '../types';
import { isLevel } from './levels';

const PAIR = /"village_id":\s*"([^"]+)"[^{}]*?"level":\s*"([a-z]+)"/g;

/**
 * Village levels the analyst's tools reported (output_summary is JSON, maybe
 * cut short). The map then shows the same levels as the answer text.
 */
export function levelsFromTools(tools: ToolCall[] | null | undefined): Record<string, Level> {
  const out: Record<string, Level> = {};
  for (const tc of tools ?? []) {
    const s = typeof tc.output_summary === 'string' ? tc.output_summary : '';
    for (const m of s.matchAll(PAIR)) if (isLevel(m[2]) && !(m[1] in out)) out[m[1]] = m[2];
  }
  return out;
}
