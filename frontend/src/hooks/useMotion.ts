import { useEffect, useRef, useState, useSyncExternalStore } from 'react';

const query = '(prefers-reduced-motion: reduce)';

function subscribe(cb: () => void) {
  if (typeof window === 'undefined' || !window.matchMedia) return () => {};
  const mq = window.matchMedia(query);
  mq.addEventListener('change', cb);
  return () => mq.removeEventListener('change', cb);
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && !!window.matchMedia && window.matchMedia(query).matches;
}

export function useReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, prefersReducedMotion, () => false);
}

/** Sets `inView` once the element is at least `threshold` visible. */
export function useInView<T extends Element>(threshold = 0.2) {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(() => typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    const el = ref.current;
    if (!el || inView) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setInView(true);
          io.disconnect();
        }
      },
      { threshold },
    );
    io.observe(el);
    return () => io.disconnect();
  }, [threshold, inView]);
  return { ref, inView };
}

/** Counts from 0 to `target` once `run` is true. 1.4 s ease-out-expo. */
export function useCountUp(target: number | null, run: boolean, duration = 1400): number | null {
  const reduced = useReducedMotion();
  const [value, setValue] = useState(0);
  const instant = reduced || !target;
  useEffect(() => {
    if (target === null || !run || instant) return;
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - t0) / duration);
      const eased = p === 1 ? 1 : 1 - Math.pow(2, -10 * p);
      setValue(Math.round(target * eased));
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, run, duration, instant]);
  if (target === null) return null;
  return instant ? target : value;
}
