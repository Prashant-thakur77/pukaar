import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { countByStatus, parseReadiness } from './pilotReadiness';

const FILE = join(__dirname, '../../../data/pilot_readiness.json');

describe('parseReadiness', () => {
  it('reads the real checklist file: twelve items, each with a title, a reason and an owner in both languages', () => {
    const r = parseReadiness(JSON.parse(readFileSync(FILE, 'utf8')));
    expect(r).not.toBeNull();
    expect(r!.items).toHaveLength(12);
    expect(r!.updated).toMatch(/^\d{4}-\d{2}-\d{2}$/);
    for (const i of r!.items) {
      expect(i.title.en && i.title.hi && i.why.en && i.why.hi && i.owner.en && i.owner.hi).toBeTruthy();
    }
    const c = countByStatus(r!.items);
    expect(c.done + c.in_progress + c.not_started).toBe(12);
  });

  it('shows an unknown status as not started, never as done', () => {
    const r = parseReadiness({ items: [{ id: 'x', status: 'finished', title: { en: 'X' } }] });
    expect(r!.items[0].status).toBe('not_started');
    expect(r!.items[0].title).toEqual({ en: 'X', hi: 'X' });
  });

  it('skips items with no id or title, and rejects a file with no items', () => {
    const r = parseReadiness({
      items: [{ status: 'done' }, { id: 'y', title: {} }, null, { id: 'z', status: 'done', title: { hi: 'ज़' } }],
    });
    expect(r!.items.map((i) => i.id)).toEqual(['z']);
    expect(parseReadiness({})).toBeNull();
    expect(parseReadiness(null)).toBeNull();
  });
});
