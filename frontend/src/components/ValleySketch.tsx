import { dict } from '../i18n';
import { levelIsKnown } from '../lib/dataStatus';
import type { PublicVillage } from '../types';

/**
 * The valley, drawn by hand and static: two ridge lines, the Beas from the Seraj valley down to Sujanpur, and the
 * five villages as discs in their live level colour. Schematic, not a map. It is the seam for the live valley
 * (S2): same positions, same data, motion added later and only under prefers-reduced-motion: no-preference.
 * Labels are HTML over the drawing so they never shrink below 16 px on a phone. The rows beside it are the links;
 * the drawing is read as one figure (its label names the five).
 */
const SPOTS: Record<string, [number, number]> = {
  janjehli: [96, 112],
  thunag: [190, 146],
  gohar: [318, 168],
  pandoh: [420, 150],
  sujanpur: [566, 196],
};
const W = 640;
const H = 260;

export function ValleySketch({ villages }: { villages: Pick<PublicVillage, 'id' | 'name' | 'name_hi' | 'level' | 'data_status' | 'data_ok_at'>[] }) {
  const placed = villages.filter((v) => SPOTS[v.id]);
  return (
    <figure className="valley" aria-label="पाँच गाँव, ब्यास घाटी · The five villages in the Beas valley">
      <svg viewBox={`0 0 ${W} ${H}`} aria-hidden="true" focusable="false" preserveAspectRatio="xMidYMid meet">
        <path className="valley-ridge" d="M0 92 L58 50 L104 78 L160 30 L214 66 L276 38 L330 74 L392 28 L452 70 L506 44 L560 80 L604 58 L640 76" />
        <path className="valley-ridge is-far" d="M0 128 L70 96 L132 118 L198 82 L262 112 L330 90 L398 120 L470 92 L540 124 L640 104" />
        <path className="valley-river" d="M20 98 C 60 104, 76 116, 96 112 S 150 138, 190 146 S 268 176, 318 168 S 390 146, 420 150 S 520 196, 566 196 S 620 214, 640 218" />
        {placed.map((v) => {
          const [x, y] = SPOTS[v.id];
          const shown = levelIsKnown(v) ? v.level : 'nodata';
          return <circle key={v.id} className={`valley-dot lv-${shown}`} cx={x} cy={y} r={8} />;
        })}
      </svg>
      {placed.map((v) => {
        const [x, y] = SPOTS[v.id];
        const unknown = !levelIsKnown(v);
        const raised = v.level !== 'normal';
        return (
          <span
            key={v.id}
            aria-hidden="true"
            className={`valley-label${y > 160 ? ' is-below' : ''}`}
            style={{ left: `${(x / W) * 100}%`, top: `${(y / H) * 100}%` }}
          >
            <span lang="hi">{v.name_hi}</span>
            {raised && <span className={`valley-level lv-${v.level}`} lang="hi"> · {dict[`level.${v.level}`].hi}</span>}
            {unknown && <span className="valley-level lv-nodata" lang="hi"> · डेटा नहीं</span>}
          </span>
        );
      })}
    </figure>
  );
}
