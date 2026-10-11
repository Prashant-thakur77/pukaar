import type { ReactNode } from 'react';

/*
 * Hand-drawn line art for Pukaar, all original and all decoration (aria-hidden, currentColor strokes).
 *  - Lehar: the kicker ornament. Two water curls roll toward a snow peak; two call rings rise over it.
 *  - Kicker: the ornament beside a small label, framed by fading hairlines.
 *  - Valley: a panorama of the Beas valley in line: snow ridges, deodars, slate-roofed kath-kuni houses,
 *    the river with the bridge and its gauge, and the call going out. `quiet` drops the village for headers.
 */

export function Lehar({ className = '' }: { className?: string }) {
  return (
    <svg className={`lehar ${className}`} viewBox="0 0 160 32" width="80" height="16" aria-hidden="true" focusable="false">
      <g fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        <path className="lehar-line" d="M3 27 H40 M120 27 H157" />
        <path d="M30 27 C 40 27, 46 23, 48 17 C 50 11, 58 9, 62 13 C 65 16, 63 21, 59 21 C 56 21, 55 18, 57 16" />
        <path d="M130 27 C 120 27, 114 23, 112 17 C 110 11, 102 9, 98 13 C 95 16, 97 21, 101 21 C 104 21, 105 18, 103 16" />
        <path d="M68 27 L80 10 L92 27" />
        <path d="M75 17.5 L78 19.5 L80 16.8 L82 19.5 L85 17.5" />
        <path className="lehar-call" d="M75 6.5 A6 6 0 0 1 85 6.5 M71.5 3.5 A11 11 0 0 1 88.5 3.5" />
      </g>
    </svg>
  );
}

export function Kicker({ children, className = '', as: Tag = 'p', id }: { children: ReactNode; className?: string; as?: 'p' | 'span'; id?: string }) {
  return (
    <Tag className={`kicker ${className}`} id={id}>
      <Lehar />
      <span className="kicker-text">{children}</span>
    </Tag>
  );
}

/** A deodar: stacked boughs on a short trunk, standing at (x, y), h tall. */
function deodar(x: number, y: number, h: number): string {
  const w = h * 0.34;
  const t = (f: number) => (y - h * f).toFixed(1);
  return (
    `M${x} ${t(1)} L${x - w * 0.55} ${t(0.62)} L${x - w * 0.3} ${t(0.62)} L${x - w * 0.8} ${t(0.3)} L${x - w * 0.42} ${t(0.3)} ` +
    `L${x - w} ${t(0.12)} L${x + w} ${t(0.12)} L${x + w * 0.42} ${t(0.3)} L${x + w * 0.8} ${t(0.3)} L${x + w * 0.3} ${t(0.62)} ` +
    `L${x + w * 0.55} ${t(0.62)} Z M${x} ${t(0.12)} V${y}`
  );
}

/** A kath-kuni house: stone-and-timber walls under a wide slate roof, a small door. */
function house(x: number, y: number, s = 1): string {
  const W = 11 * s;
  const H = 12 * s;
  return (
    `M${x - W} ${y} V${y - H} M${x + W} ${y} V${y - H} M${x - W} ${y - H * 0.5} H${x + W} ` +
    `M${x - W - 5 * s} ${y - H + 1} L${x} ${y - H - 11 * s} L${x + W + 5 * s} ${y - H + 1} Z ` +
    `M${x - 2.5 * s} ${y} V${y - 6 * s} H${x + 2.5 * s} V${y}`
  );
}

const TREES: [number, number, number][] = [
  [118, 137, 30], [136, 136, 22], [330, 129, 26], [348, 130, 19], [712, 127, 24], [1004, 142, 30], [1022, 141, 22], [1104, 134, 26],
];
const HOUSES: [number, number, number][] = [
  [548, 141, 1], [582, 138, 0.85], [902, 143, 1],
];
const RAIN = [
  [40, 14], [74, 30], [108, 8], [142, 26], [176, 12], [1010, 10], [1044, 28], [1078, 6], [1112, 22], [1146, 12], [1180, 30],
];

export function ValleyLine({ className = '', quiet = false }: { className?: string; quiet?: boolean }) {
  return (
    <svg
      className={`valley-art${quiet ? ' is-quiet' : ''} ${className}`}
      viewBox={quiet ? '0 36 1200 164' : '0 0 1200 200'}
      preserveAspectRatio={quiet ? 'none' : 'xMidYMax meet'}
      aria-hidden="true"
      focusable="false"
    >
      <g fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round">
        {!quiet && (
          <path
            className="va-rain"
            d={RAIN.map(([x, y]) => `M${x} ${y} l-5 13`).join(' ')}
            strokeWidth="1"
          />
        )}
        <path
          className="va-far"
          strokeWidth="1.1"
          d="M0 120 L60 96 L95 110 L150 64 L178 80 L210 58 L250 92 L300 74 L352 104 L410 70 L440 82 L486 40 L520 66 L560 52 L610 92 L660 80 L720 108 L780 72 L812 86 L860 46 L900 70 L940 60 L990 98 L1040 84 L1090 110 L1140 88 L1200 104"
        />
        <path
          className="va-snow"
          strokeWidth="1.1"
          d="M474 52 L480 56 L486 50 L492 56 L498 51 M848 58 L854 62 L860 56 L866 62 L872 57 M200 68 L205 71 L210 66 L215 71 L220 68"
        />
        <path
          className="va-near"
          strokeWidth="1.3"
          d="M0 150 C 80 132, 140 128, 210 140 S 330 120, 400 134 S 520 150, 600 136 S 760 118, 840 136 S 980 150, 1060 134 S 1160 128, 1200 138"
        />
        {!quiet && <path className="va-trees" strokeWidth="1.2" d={TREES.map(([x, y, h]) => deodar(x, y, h)).join(' ')} />}
        {!quiet && <path className="va-houses" strokeWidth="1.2" d={HOUSES.map(([x, y, s]) => house(x, y, s)).join(' ')} />}
        <path
          className="va-river"
          strokeWidth="1.4"
          d="M0 178 C 150 168, 260 190, 420 178 S 700 160, 860 176 S 1080 192, 1200 176 M0 190 C 160 180, 270 200, 430 189 S 700 172, 862 187 S 1080 202, 1200 188"
        />
        <path className="va-ripple" strokeWidth="1" d="M200 186 h16 M512 176 h12 M758 180 h18 M980 192 h14 M330 188 h10 M1120 184 h12" />
        {!quiet && (
          <>
            <path className="va-bridge" strokeWidth="1.3" d="M606 172 Q 640 150 674 172 M600 168 H680 M652 168 V186 M652 173 h5 M652 178 h5 M652 183 h5" />
            <path className="va-call" strokeWidth="1.2" d="M645 158 A9 9 0 0 1 659 158 M640 152 A16 16 0 0 1 664 152 M635 146 A23 23 0 0 1 669 146" />
          </>
        )}
      </g>
    </svg>
  );
}

/** A quiet field of Hindi words about water, set like type on a press bed. Decoration only. */
const WORDS = ['नदी', 'पानी', 'बारिश', 'पुकार', 'गाँव', 'पुल', 'ढलान', 'बादल', 'धारा', 'सुरक्षित', 'मिल गया', 'ब्यास'];
export function WordField({ className = '' }: { className?: string }) {
  return (
    <div className={`word-field ${className}`} aria-hidden="true" lang="hi">
      {Array.from({ length: 4 }, (_, row) => (
        <span key={row}>{[...WORDS.slice(row * 3), ...WORDS.slice(0, row * 3)].join(' · ')}</span>
      ))}
    </div>
  );
}
