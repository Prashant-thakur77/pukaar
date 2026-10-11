import { useCallback, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties } from 'react';
import { createPortal } from 'react-dom';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, ArrowRight, ArrowUpRight, Compass } from 'lucide-react';
import { useReducedMotion } from '../hooks/useMotion';
import { useT } from '../i18n';
import { END_TEXT, placePopover, RING_PAD, scrollTargetY, TOUR_LENGTH, TOUR_STEPS, useTour, type Box } from '../lib/tour';

const WAIT_MS = 4000;
/** A page still showing skeletons is still loading its data: keep waiting, up to this long. */
const WAIT_LOADING_MS = 12000;
const GLIDE_MS = 250;
const GITHUB = 'https://github.com/Prashant-thakur77/pukaar';
const NARROW = '(max-width: 419px)';

function useMedia(query: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(query);
      mq.addEventListener('change', cb);
      return () => mq.removeEventListener('change', cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

/** The bottom edge of whatever is stuck to the top of the viewport (the header, and the replay banner under it). */
function topInset(): number {
  let bottom = 0;
  for (const sel of ['.site-header', '.replay-banner']) {
    const r = document.querySelector(sel)?.getBoundingClientRect();
    if (r && r.height > 0 && r.top <= bottom + 1 && r.bottom > bottom) bottom = r.bottom;
  }
  return bottom;
}

/**
 * Calls back with the first of `sels` (in priority order) that is on the page with a size, or null after `ms`
 * (or, while the page still shows loading skeletons, after `WAIT_LOADING_MS`). Watches the DOM, because the
 * target usually arrives with the page's data.
 */
function waitForAny(sels: string[], ms: number, cb: (el: HTMLElement | null, idx: number) => void): () => void {
  const find = (): [HTMLElement, number] | null => {
    for (let i = 0; i < sels.length; i++) {
      const el = document.querySelector(sels[i]);
      if (el instanceof HTMLElement && el.getBoundingClientRect().height > 0) return [el, i];
    }
    return null;
  };
  let done = false;
  const finish = (r: [HTMLElement, number] | null) => {
    if (done) return;
    done = true;
    stop();
    cb(r ? r[0] : null, r ? r[1] : -1);
  };
  const mo = new MutationObserver(() => {
    const r = find();
    if (r) finish(r);
  });
  const t0 = Date.now();
  let tm = 0;
  const giveUp = () => {
    const r = find();
    if (!r && document.querySelector('#main .skel') && Date.now() - t0 < WAIT_LOADING_MS) tm = window.setTimeout(giveUp, 400);
    else finish(r);
  };
  tm = window.setTimeout(giveUp, ms);
  // First look on the next frame, after the page (and the Shell's scroll reset) has committed.
  const raf = requestAnimationFrame(() => {
    const r = find();
    if (r) finish(r);
  });
  mo.observe(document.body, { childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'data-tour'] });
  function stop() {
    mo.disconnect();
    clearTimeout(tm);
    cancelAnimationFrame(raf);
  }
  return () => {
    done = true;
    stop();
  };
}

/** Smooth-scrolls to `y` and resolves when the scroll settles (or at once, if there is nowhere to go). */
function scrollAndSettle(y: number, smooth: boolean, onDone: () => void): () => void {
  const max = document.documentElement.scrollHeight - window.innerHeight;
  const to = Math.max(0, Math.min(y, max));
  if (Math.abs(window.scrollY - to) < 2) {
    const raf = requestAnimationFrame(onDone);
    return () => cancelAnimationFrame(raf);
  }
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    window.removeEventListener('scrollend', finish);
    clearTimeout(tm);
    onDone();
  };
  window.addEventListener('scrollend', finish);
  const tm = window.setTimeout(finish, smooth ? 900 : 60);
  window.scrollTo({ top: to, behavior: smooth ? 'smooth' : 'auto' });
  return () => {
    done = true;
    window.removeEventListener('scrollend', finish);
    clearTimeout(tm);
  };
}

const sameBox = (a: Box | null, b: Box) =>
  !!a && Math.abs(a.top - b.top) < 0.5 && Math.abs(a.left - b.left) < 0.5 && Math.abs(a.width - b.width) < 0.5 && Math.abs(a.height - b.height) < 0.5;

/** Entry point: a pill that starts the tour. */
export function TourButton({ className = '' }: { className?: string }) {
  const { lang } = useT();
  const seen = useTour((s) => s.seen);
  const start = useTour((s) => s.start);
  const en = lang === 'en';
  return (
    <button type="button" className={`tour-pill ${className}`} onClick={start} aria-haspopup="dialog">
      <Compass aria-hidden="true" />
      {seen ? (en ? 'See the 60-second tour again' : '60 सेकंड का टूर फिर देखें') : en ? 'Take the 60-second tour' : '60 सेकंड का टूर देखें'}
    </button>
  );
}

/** Mounted once in the Shell: starts the tour from `?tour=1` and renders it while it runs. */
export function TourHost() {
  const { search, pathname, hash } = useLocation();
  const navigate = useNavigate();
  const active = useTour((s) => s.active);
  useEffect(() => {
    const q = new URLSearchParams(search);
    if (q.get('tour') !== '1') return;
    q.delete('tour');
    const rest = q.toString();
    navigate({ pathname, search: rest ? `?${rest}` : '', hash }, { replace: true });
    useTour.getState().start();
  }, [search, pathname, hash, navigate]);
  return active ? <TourOverlay /> : null;
}

type Found = { step: number; el: HTMLElement; idx: number };

function TourOverlay() {
  const { lang } = useT();
  const en = lang === 'en';
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const step = useTour((s) => s.step);
  const { next, back, close, skipMissing } = useTour.getState();
  const reduced = useReducedMotion();
  const narrow = useMedia(NARROW);

  const [found, setFound] = useState<Found | null>(null);
  const [rect, setRect] = useState<Box | null>(null);
  const [vp, setVp] = useState(() => ({ width: window.innerWidth, height: window.innerHeight, top0: topInset() }));
  const [pop, setPop] = useState({ width: 320, height: 220 });
  const [gliding, setGliding] = useState(false);
  const popRef = useRef<HTMLDivElement>(null);
  const primaryRef = useRef<HTMLButtonElement>(null);
  /** The step we last navigated for, the path we left, and whether we got there. */
  const navFor = useRef({ step: -1, from: '', arrived: false });

  const s = TOUR_STEPS[step];
  const isEnd = s.targets.length === 0;
  const current = found && found.step === step ? found : null;
  const resolving = !isEnd && !current;
  // Until a target is found, the step's first candidate supplies the words.
  const text = isEnd ? END_TEXT : s.targets[current ? current.idx : 0];

  // Go to the step's page, find its target, frame it, then light the ring.
  useEffect(() => {
    if (s.route && pathname !== s.route) {
      const nav = navFor.current;
      if (nav.step === step) {
        // Our own navigation has not landed yet (or this effect ran twice): wait for it.
        if (!nav.arrived && pathname === nav.from) return;
        // The visitor went somewhere else (e.g. browser Back): end the tour, do not drag them back.
        close();
        return;
      }
      navFor.current = { step, from: pathname, arrived: false };
      navigate(s.route);
      return;
    }
    navFor.current = { step, from: pathname, arrived: true };
    if (isEnd) return;
    let cancelScroll: (() => void) | null = null;
    let glideOff = 0;
    const cancelWait = waitForAny(
      s.targets.map((t) => t.sel),
      WAIT_MS,
      (el, idx) => {
        if (!el) {
          skipMissing();
          return;
        }
        const top0 = topInset();
        const reserve = popRef.current?.offsetHeight ?? 220;
        const y = scrollTargetY(el.getBoundingClientRect(), window.scrollY, window.innerHeight, top0, reserve);
        cancelScroll = scrollAndSettle(y, !reduced, () => {
          // Light the ring and let it glide there once; afterwards it sticks to the target while the page scrolls.
          setGliding(true);
          setFound({ step, el, idx });
          glideOff = window.setTimeout(() => setGliding(false), GLIDE_MS + 80);
        });
      },
    );
    return () => {
      cancelWait();
      cancelScroll?.();
      clearTimeout(glideOff);
    };
  }, [step, pathname, s, isEnd, navigate, close, skipMissing, reduced]);

  // Track the target (layout shifts, scrolling, resizing) every frame. While the next step loads, the ring
  // stays (unlit) on the last target if it is still on the page; once that page is gone it closes to a point.
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      if (found?.el.isConnected) {
        const r = found.el.getBoundingClientRect();
        const b = { top: r.top, left: r.left, width: r.width, height: r.height };
        setRect((old) => (sameBox(old, b) ? old : b));
      } else setRect(null);
      const v = { width: window.innerWidth, height: window.innerHeight, top0: topInset() };
      setVp((old) => (old.width === v.width && old.height === v.height && old.top0 === v.top0 ? old : v));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [found]);

  // Measure the popover so it can be placed without overflowing.
  useLayoutEffect(() => {
    const el = popRef.current;
    if (!el) return;
    const measure = () => setPop((old) => (old.width === el.offsetWidth && old.height === el.offsetHeight ? old : { width: el.offsetWidth, height: el.offsetHeight }));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  // Modal: the app behind is inert while the tour runs; focus comes back to where it was.
  useEffect(() => {
    const root = document.getElementById('root');
    const before = document.activeElement as HTMLElement | null;
    root?.setAttribute('inert', '');
    return () => {
      root?.removeAttribute('inert');
      if (before && before.isConnected) before.focus({ preventScroll: true });
      else document.getElementById('main')?.focus({ preventScroll: true });
    };
  }, []);

  // Keep focus in the popover on every step (the Back button disappears on step 1, for one).
  useEffect(() => {
    if (!popRef.current?.contains(document.activeElement)) primaryRef.current?.focus({ preventScroll: true });
  }, [step]);

  const onKey = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        close();
      } else if (e.key === 'ArrowRight') {
        e.preventDefault();
        next();
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault();
        back();
      } else if (e.key === 'Tab') {
        const items = Array.from(popRef.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])') ?? []);
        if (items.length === 0) return;
        const i = items.indexOf(document.activeElement as HTMLElement);
        const to = e.shiftKey ? (i <= 0 ? items.length - 1 : i - 1) : i === -1 || i === items.length - 1 ? 0 : i + 1;
        e.preventDefault();
        items[to].focus();
      }
    },
    [close, next, back],
  );
  useEffect(() => {
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [onKey]);

  // Ring geometry: the target plus padding; a point in the middle of the screen for the end card or when there is
  // nothing on the page to hold on to.
  const ringBox: Box | null = isEnd
    ? { top: vp.height / 2, left: vp.width / 2, width: 0, height: 0 }
    : rect
      ? { top: rect.top - RING_PAD, left: rect.left - RING_PAD, width: rect.width + RING_PAD * 2, height: rect.height + RING_PAD * 2 }
      : { top: vp.height / 2, left: vp.width / 2, width: 0, height: 0 };
  const lit = Boolean(current && rect);

  const place = narrow ? null : placePopover(isEnd ? null : rect, pop, vp, vp.top0);
  const popStyle: CSSProperties | undefined = place ? { top: place.top, left: place.left } : undefined;
  const glide = !reduced && (gliding || isEnd);

  const n = step + 1;
  const announce = `${en ? `Step ${n} of ${TOUR_LENGTH}` : `${TOUR_LENGTH} में से ${n}`}: ${text.title[lang]}. ${text.body[lang]}`;
  const finish = () => close();

  return createPortal(
    <div className={`tour${narrow ? ' is-sheet' : ''}${glide ? ' is-glide' : ''}`} role="dialog" aria-modal="true" aria-labelledby="tour-title" aria-describedby="tour-body" lang={lang}>
      <div className={`tour-ring${lit ? ' is-lit' : ''}`} style={ringBox} aria-hidden="true" />
      <div ref={popRef} className={`tour-pop${isEnd ? ' is-end' : ''}${place ? ` at-${place.side}` : ''}`} style={popStyle}>
        <div className="tour-top">
          <span className="tour-count">{en ? `Step ${n} / ${TOUR_LENGTH}` : `${n} / ${TOUR_LENGTH}`}</span>
          <ol className="tour-dots" aria-hidden="true">
            {TOUR_STEPS.map((_, i) => (
              <li key={i} className={i === step ? 'is-on' : i < step ? 'is-done' : ''} />
            ))}
          </ol>
        </div>
        <h2 id="tour-title" className="tour-title">
          {text.title[lang]}
        </h2>
        <p id="tour-body" className="tour-body">
          {text.body[lang]}
        </p>
        {resolving && <p className="tour-wait">{en ? 'Loading this part…' : 'यह हिस्सा लोड हो रहा है…'}</p>}
        {isEnd && (
          <div className="tour-ctas">
            <Link to="/live" className="btn btn-sm btn-accent" onClick={finish}>
              {en ? 'See it live' : 'लाइव देखें'}
            </Link>
            <Link to="/report" className="btn btn-sm btn-ink" onClick={finish}>
              {en ? 'Report' : 'सूचना दें'}
            </Link>
            <a href={GITHUB} target="_blank" rel="noreferrer" className="btn btn-sm btn-ghost tour-code" onClick={finish}>
              {en ? 'Code' : 'कोड'} <ArrowUpRight aria-hidden="true" />
            </a>
          </div>
        )}
        <div className="tour-actions">
          <button type="button" className="tour-skip" onClick={close}>
            {isEnd ? (en ? 'Close' : 'बंद करें') : en ? 'Skip tour' : 'टूर छोड़ें'}
          </button>
          {step > 0 && (
            <button type="button" className="btn btn-sm btn-ghost tour-back" onClick={back} aria-label={en ? 'Back' : 'पीछे'}>
              <ArrowLeft aria-hidden="true" />
              <span className="tour-back-word">{en ? 'Back' : 'पीछे'}</span>
            </button>
          )}
          <button ref={primaryRef} type="button" className="btn btn-sm btn-accent tour-next" onClick={isEnd ? finish : next}>
            {isEnd ? (en ? 'Finish' : 'पूरा हुआ') : en ? 'Next' : 'आगे'}
            {!isEnd && <ArrowRight aria-hidden="true" />}
          </button>
        </div>
        <p className="sr-only" aria-live="polite" aria-atomic="true">
          {resolving ? '' : announce}
        </p>
      </div>
    </div>,
    document.body,
  );
}
