import { describe, expect, it } from 'vitest';
import { levelsFromTools } from './ask';

describe('levelsFromTools', () => {
  it('reads village levels from tool output, even when cut short', () => {
    const tools = [
      { name: 'rank_villages', input: {}, decision: 'allow', output_summary: '[{"village_id": "sujanpur", "name": "Sujanpur", "level": "warning", "rain_24h_mm": 8.5}, {"village_id": "gohar", "name": "Gohar", "level": "watch", "rain' },
      { name: 'query_deliveries', input: {}, decision: 'allow', output_summary: '[]' },
    ];
    expect(levelsFromTools(tools)).toEqual({ sujanpur: 'warning', gohar: 'watch' });
    expect(levelsFromTools(null)).toEqual({});
  });
});
