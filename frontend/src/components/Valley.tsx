import { useEffect, useRef } from 'react';
import { prefersReducedMotion } from '../hooks/useMotion';

/* Deterministic star field so the hero renders the same every time. */
function stars(n: number) {
  let s = 7;
  const r = () => {
    s = (s * 16807) % 2147483647;
    return s / 2147483647;
  };
  return Array.from({ length: n }, () => ({ x: r() * 1440, y: r() * 380, r: r() * 1.3 + 0.3, o: r() * 0.6 + 0.2 }));
}
const STARS = stars(70);

/**
 * Layered Himalayan ridges at night with a glowing river, call rings and a
 * one-off echo that travels to the left ridge and returns, weaker, to the right.
 * Ridges drift at different speeds on scroll (capped, off for reduced motion).
 */
export function Valley() {
  const ref = useRef<SVGSVGElement>(null);
  useEffect(() => {
    if (prefersReducedMotion()) return;
    const el = ref.current;
    if (!el) return;
    let raf = 0;
    const onScroll = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => {
        const y = Math.min(window.scrollY, 400);
        el.style.setProperty('--py', String(y));
      });
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => {
      window.removeEventListener('scroll', onScroll);
      cancelAnimationFrame(raf);
    };
  }, []);

  return (
    <svg ref={ref} className="valley" viewBox="0 0 1440 900" preserveAspectRatio="xMidYMax slice" aria-hidden="true" focusable="false">
      <defs>
        <radialGradient id="vg-sky" cx="50%" cy="38%" r="75%">
          <stop offset="0" stopColor="#1f2a5c" />
          <stop offset="0.55" stopColor="#0f1636" />
          <stop offset="1" stopColor="#070b1d" />
        </radialGradient>
        <linearGradient id="vg-r1" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#3a4785" />
          <stop offset="1" stopColor="#1b2350" />
        </linearGradient>
        <linearGradient id="vg-r2" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#28336a" />
          <stop offset="1" stopColor="#141b40" />
        </linearGradient>
        <linearGradient id="vg-r3" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#1a2250" />
          <stop offset="1" stopColor="#0d1330" />
        </linearGradient>
        <linearGradient id="vg-r4" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#10173a" />
          <stop offset="1" stopColor="#070b1d" />
        </linearGradient>
        <linearGradient id="vg-river" x1="0" x2="1">
          <stop offset="0" stopColor="#f5a524" stopOpacity="0" />
          <stop offset="0.45" stopColor="#ffc35c" stopOpacity="0.9" />
          <stop offset="1" stopColor="#f5a524" stopOpacity="0" />
        </linearGradient>
        <filter id="vg-glow" x="-20%" y="-50%" width="140%" height="200%">
          <feGaussianBlur stdDeviation="6" />
        </filter>
      </defs>
      <rect width="1440" height="900" fill="url(#vg-sky)" />
      <g className="v-stars">
        {STARS.map((s, i) => (
          <circle key={i} cx={s.x} cy={s.y} r={s.r} fill="#dfe5ff" opacity={s.o} />
        ))}
      </g>
      {/* snow-capped far range */}
      <g className="v-layer v-l1">
        <path fill="url(#vg-r1)" d="M0 520 L90 470 L160 488 L250 405 L320 440 L410 360 L470 392 L560 318 L640 372 L720 300 L800 352 L880 310 L960 380 L1040 330 L1120 398 L1200 350 L1290 420 L1360 380 L1440 430 V900 H0Z" />
        <path fill="#cfd8ff" opacity="0.28" d="M410 360 L470 392 L448 390 L430 378 L414 384Z M560 318 L604 346 L580 344 L566 336 L552 340Z M720 300 L768 334 L742 330 L728 320 L708 326Z M880 310 L920 336 L900 334 L884 326 L868 330Z M1040 330 L1080 358 L1056 354 L1044 348 L1028 352Z" />
      </g>
      <g className="v-layer v-l2">
        <path fill="url(#vg-r2)" d="M0 600 L120 530 L220 575 L330 500 L430 560 L520 515 L600 572 L700 540 L780 590 L870 528 L980 580 L1080 520 L1180 572 L1280 520 L1380 566 L1440 545 V900 H0Z" />
      </g>
      <g className="v-layer v-l3">
        <path fill="url(#vg-r3)" d="M0 680 L80 640 L190 690 L300 610 L420 676 L520 640 L610 700 L840 700 L930 640 L1040 690 L1150 618 L1260 676 L1360 640 L1440 668 V900 H0Z" />
        {/* village lights */}
        <g className="v-lights">
          <circle cx="300" cy="640" r="2.4" fill="#ffc35c" />
          <circle cx="312" cy="646" r="1.8" fill="#ffc35c" />
          <circle cx="1150" cy="648" r="2.4" fill="#ffc35c" />
          <circle cx="1162" cy="655" r="1.6" fill="#ffc35c" />
          <circle cx="930" cy="668" r="2" fill="#ffc35c" />
          <circle cx="520" cy="668" r="2" fill="#ffc35c" />
        </g>
      </g>
      {/* river along the valley floor */}
      <g className="v-river">
        <path d="M-20 820 C 240 790, 420 760, 640 742 S 980 760, 1140 800 S 1380 840, 1460 836" stroke="url(#vg-river)" strokeWidth="10" fill="none" filter="url(#vg-glow)" opacity="0.7" />
        <path className="v-river-line" d="M-20 820 C 240 790, 420 760, 640 742 S 980 760, 1140 800 S 1380 840, 1460 836" stroke="url(#vg-river)" strokeWidth="2.5" fill="none" />
      </g>
      <g className="v-layer v-l4">
        <path fill="url(#vg-r4)" d="M0 760 L140 720 L260 770 L380 730 L470 790 L560 900 L0 900Z M1440 740 L1320 720 L1200 770 L1090 740 L980 800 L900 900 L1440 900Z" />
      </g>
      {/* echo: an arc travels to the left ridge, a weaker one returns to the right */}
      <g className="v-echo" fill="none" stroke="#ffc35c" strokeLinecap="round">
        <path className="echo-l" d="M700 330 A 60 60 0 0 0 700 450" strokeWidth="3" />
        <path className="echo-r" d="M740 330 A 60 60 0 0 1 740 450" strokeWidth="2.5" />
      </g>
    </svg>
  );
}
