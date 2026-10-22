import { beforeEach, describe, expect, it } from 'vitest';
import { ACTIONS, NO_DATA } from './actions';
import { districtLine, istClock, isStale, LAST_VILLAGE_KEY, levelStep, minutesSince, nowFromDetail, placeLine, readCachedNow, shelterWord, writeCachedNow, type VillageNow } from './villageNow';
import { VILLAGER_THEME_PATH } from '../store';
import type { VillageDetail } from '../types';

const NOW: VillageNow = {
  id: 'gohar', name: 'Gohar', name_hi: 'गोहर', district: 'Mandi', level: 'warning', level_since: '2026-10-22T21:30:00Z',
  level_known: true, data_status: 'ok', data_ok_at: '2026-10-22T21:40:00Z', checked_at: '2026-10-22T21:40:00Z',
  means: { hi: 'तैयार रहें', en: 'Get ready' }, actions: ACTIONS.warning,
  safe_place: { id: 'p1', name: 'Civil Hospital, Gohar', name_hi: null, kind_en: 'Hospital', kind_hi: 'अस्पताल', walk_min: 25, route_length_m: 1238, headroom_m: 17, status: 'UNCONFIRMED', route_blocked: false },
};

describe('the village answer kept on the phone', () => {
  beforeEach(() => localStorage.clear());

  it('round-trips through localStorage and remembers the last village', () => {
    writeCachedNow(NOW, 1000);
    expect(readCachedNow('gohar')).toEqual({ now: NOW, fetchedAt: 1000 });
    expect(localStorage.getItem(LAST_VILLAGE_KEY)).toBe('gohar');
    expect(readCachedNow('thunag')).toBeNull();
  });

  it('ignores a broken or foreign copy instead of painting it', () => {
    localStorage.setItem('pukaar.now.gohar', '{not json');
    expect(readCachedNow('gohar')).toBeNull();
    localStorage.setItem('pukaar.now.gohar', JSON.stringify({ now: { ...NOW, id: 'thunag' }, fetchedAt: 1 }));
    expect(readCachedNow('gohar')).toBeNull();
  });
});

describe('time on the answer', () => {
  it('reads the clock in India whatever the phone says', () => {
    expect(istClock('2026-10-22T21:40:00Z')).toBe('03:10 IST');
    expect(istClock(null)).toBeNull();
    expect(istClock('nonsense')).toBeNull();
  });

  it('calls an answer older than an hour stale', () => {
    const t = Date.parse('2026-10-22T21:40:00Z');
    expect(minutesSince('2026-10-22T21:40:00Z', t + 4 * 60000)).toBe(4);
    expect(isStale('2026-10-22T21:40:00Z', t + 59 * 60000)).toBe(false);
    expect(isStale('2026-10-22T21:40:00Z', t + 61 * 60000)).toBe(true);
  });
});

describe('words on the answer', () => {
  it('places the level on the four-step scale', () => {
    expect([levelStep('normal'), levelStep('watch'), levelStep('warning'), levelStep('critical')]).toEqual([1, 2, 3, 4]);
  });

  it('says where to go in a few words, and the ledger state as a word', () => {
    expect(placeLine(NOW.safe_place, 'hi')).toBe('अस्पताल, 25 मिनट');
    expect(placeLine(NOW.safe_place, 'en')).toBe('Hospital, 25 min');
    expect(placeLine(null, 'hi')).toBeNull();
    expect(shelterWord('OPEN', 'hi')).toBe('खुला');
    expect(shelterWord('UNCONFIRMED', 'en')).toBe('Not yet checked');
    expect(districtLine('Mandi', 'hi')).toBe('ज़िला मंडी');
  });
});

describe('the answer from the full detail', () => {
  const detail = (over: Partial<VillageDetail['village']>) =>
    ({
      village: { id: 'thunag', name: 'Thunag', name_hi: 'थुनाग', district: 'Mandi', level: 'normal', level_since: null, data_status: 'ok', latest_reading: null, ...over },
      readings: [
        { at: '2026-10-22T21:25:00Z', replay: false },
        { at: '2026-10-22T21:40:00Z', replay: false },
        { at: '2023-07-09T00:00:00Z', replay: true },
      ],
    }) as unknown as VillageDetail;

  it('takes the newest live reading as the check time', () => {
    const n = nowFromDetail(detail({}));
    expect(n.checked_at).toBe('2026-10-22T21:40:00Z');
    expect(n.actions).toEqual(ACTIONS.normal);
    expect(n.level_known).toBe(true);
  });

  it('never says Normal without data: the no-data lines instead', () => {
    const n = nowFromDetail(detail({ data_status: 'unavailable' }));
    expect(n.level_known).toBe(false);
    expect(n.actions).toEqual(NO_DATA);
  });

  it('keeps at most three actions per level', () => {
    for (const lines of Object.values(ACTIONS)) expect(lines.length).toBeLessThanOrEqual(3);
  });
});

describe('light by default for villagers', () => {
  it('covers the pages a villager opens, not the officer pages', () => {
    for (const p of ['/', '/village/gohar', '/report', '/t/PK-1234', '/safe/abc', '/live']) expect(VILLAGER_THEME_PATH.test(p), p).toBe(true);
    for (const p of ['/console', '/roster', '/audit', '/a/tok', '/login', '/how', '/pilot']) expect(VILLAGER_THEME_PATH.test(p), p).toBe(false);
  });
});
