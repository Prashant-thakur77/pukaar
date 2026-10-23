import { useState } from 'react';
import { CloudOff, Pause, Play } from 'lucide-react';
import { dict, useT } from '../i18n';
import { levelIsKnown } from '../lib/dataStatus';
import { LEVEL_ICON, levelRank } from '../lib/levels';
import type { PublicVillage } from '../types';
import './valley.css';

/*
 * S2, the valley at night (C30): the Beas from Kullu past Pandoh and Mandi to Sujanpur, its two side streams up to
 * Gohar and into the Seraj valley, the ridges between, and the five villages as discs in their live level colour,
 * each with its level's icon (colour is never alone). Drawn by hand from the villages' real positions, the west
 * squeezed so the four Mandi villages have room; schematic, not a map. Inline SVG, no image, no library.
 * Motion only under prefers-reduced-motion: no-preference: the river draws once; a village at Watch or above
 * sends out one ring every 8 s, with a pause button. Hovering or tapping a village lights its row (and back).
 */

/** Where each village sits in the 720 × 400 drawing (from its latitude and longitude, see above), and its name's side. */
const SPOT: Record<string, [number, number]> = {
  sujanpur: [74, 136],
  pandoh: [470, 244],
  gohar: [452, 306],
  thunag: [594, 318],
  janjehli: [656, 346],
};
const SIDE: Record<string, 'r' | 't' | 'b'> = { thunag: 't', janjehli: 'b' };
const W = 720;
const H = 400;

type V = Pick<PublicVillage, 'id' | 'name' | 'name_hi' | 'level' | 'data_status' | 'data_ok_at'>;

export function ValleyMap({ villages, hot = null, onHot, still = false, className = '' }: { villages: V[]; hot?: string | null; onHot?: (id: string | null) => void; still?: boolean; className?: string }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const [paused, setPaused] = useState(false);
  const placed = villages.filter((v) => SPOT[v.id]);
  const rings = !still && placed.some((v) => levelIsKnown(v) && levelRank(v.level) >= levelRank('watch'));
  const label = hi
    ? `ब्यास घाटी के पाँच गाँव: ${placed.map((v) => `${v.name_hi} ${levelIsKnown(v) ? dict[`level.${v.level}`].hi : 'डेटा नहीं'}`).join(', ')}`
    : `The five villages of the Beas valley: ${placed.map((v) => `${v.name} ${levelIsKnown(v) ? dict[`level.${v.level}`].en : 'no data'}`).join(', ')}`;
  return (
    <figure className={`vm${paused ? ' is-paused' : ''}${still ? ' is-still' : ''} ${className}`}>
      <div className="vm-art" role="img" aria-label={label}>
        <svg viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false">
          <g className="vm-ridges">
            <path d="M0 58c40-20 62-6 96-24s58 8 92-6 52-24 86-4 50 22 88 2 60-26 98-10 46 18 82 2 60-12 90 2 50 6 88-4" />
            <path className="is-near" d="M0 96c34-10 58 6 92-10s60-6 90 8 44 14 78-4 54-30 90-16 40 26 74 18 42-36 80-28 52 22 92 10 48-14 94-2" />
            <path d="M150 262c30-12 52 2 80-10s48-22 76-8 38 26 70 14" />
            <path className="is-near" d="M196 330c36-18 62-2 94-16s52-20 84-6 30 30 62 22 44-30 80-26 40 20 70 12" />
            <path d="M330 392c40-22 72-6 104-20s64-26 98-8 52 22 92 6 60-26 96-8" />
            <path className="is-near" d="M520 214c26-16 44-6 66-18s42-18 70-4 38 12 64 0" />
          </g>
          <g className="vm-streams">
            <path d="M656 346c-20-6-36-16-62-28s-30-34-50-44-50-22-70-28" />
            <path d="M452 306c-4-14 2-26-8-38s-18-18-24-24" />
          </g>
          <path
            className="vm-river"
            pathLength={1}
            d="M548 0c6 30 18 62 16 100s-6 64-14 90-40 42-80 54-58 10-90 0-30-22-50-26-38-14-62-26-50-18-76-22-46-12-70-14-38-18-60-22-34-2-58 2"
          />
          <circle className="vm-town" cx="330" cy="218" r="5" />
        </svg>
        <span className="vm-word vm-beas" lang={hi ? 'hi' : 'en'} style={{ left: '71%', top: '28%' }}>
          {hi ? 'ब्यास' : 'Beas'}
        </span>
        <span className="vm-word vm-town-word" lang={hi ? 'hi' : 'en'} style={{ left: `${(330 / W) * 100}%`, top: `${(218 / H) * 100}%` }}>
          {hi ? 'मंडी' : 'Mandi'}
        </span>
        {placed.map((v) => {
          const [x, y] = SPOT[v.id];
          const known = levelIsKnown(v);
          const Icon = known ? LEVEL_ICON[v.level] : CloudOff;
          const raised = !still && known && levelRank(v.level) >= levelRank('watch');
          return (
            <span
              key={v.id}
              className={`vm-v lv-${known ? v.level : 'nodata'}${raised ? ' is-raised' : ''}${hot === v.id ? ' is-hot' : ''} is-${SIDE[v.id] ?? 'r'}`}
              style={{ left: `${(x / W) * 100}%`, top: `${(y / H) * 100}%` }}
              onPointerEnter={() => onHot?.(v.id)}
              onPointerLeave={() => onHot?.(null)}
              onPointerDown={() => onHot?.(v.id)}
            >
              <span className="vm-mark">
                <Icon aria-hidden="true" />
              </span>
              <span className="vm-name" lang={hi ? 'hi' : 'en'}>
                {hi ? v.name_hi : v.name}
              </span>
            </span>
          );
        })}
      </div>
      {/* A phone sees the four Mandi villages closer up; Sujanpur, downstream in Hamirpur, is named at the edge. */}
      {placed
        .filter((v) => v.id === 'sujanpur')
        .map((v) => {
          const known = levelIsKnown(v);
          return (
            <span key={v.id} className={`vm-off lv-${known ? v.level : 'nodata'}`} aria-hidden="true">
              ← <i className="vm-off-dot" /> <span lang={hi ? 'hi' : 'en'}>{hi ? v.name_hi : v.name}</span>
            </span>
          );
        })}
      {rings && (
        <div className="vm-tools">
          <button type="button" className="vm-pause" onClick={() => setPaused((p) => !p)} aria-pressed={paused}>
            {paused ? <Play aria-hidden="true" /> : <Pause aria-hidden="true" />}
            <span>{paused ? (hi ? 'चलाएँ' : 'Play') : hi ? 'रोकें' : 'Pause'}</span>
          </button>
        </div>
      )}
    </figure>
  );
}
