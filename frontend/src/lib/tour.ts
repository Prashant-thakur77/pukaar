import { create } from 'zustand';
import { writeSession } from './session';

/*
 * The visitor tour: the steps (data only), a tiny store, and the pure layout maths the overlay uses.
 * Tour.tsx renders it; this module has no React components so it can be unit-tested.
 */

export type Txt = { hi: string; en: string };

/** One thing to point at. The first selector that exists on the page wins. */
export interface TourTarget {
  sel: string;
  title: Txt;
  body: Txt;
}

export interface TourStep {
  /** The route the step lives on; the end card has none and stays where the visitor is. */
  route?: string;
  /** Candidates in priority order. Empty for the end card. */
  targets: TourTarget[];
}

export const TOUR_STEPS: TourStep[] = [
  {
    route: '/',
    targets: [
      {
        sel: '[data-tour="hero"]',
        title: { en: 'What Pukaar is', hi: 'पुकार क्या है' },
        body: {
          en: 'Flood warnings for hill villages: code watches the rain and the river, an officer approves, and every phone hears the alert in Hindi.',
          hi: 'पहाड़ी गाँवों के लिए बाढ़ चेतावनी: कोड बारिश और नदी पर नज़र रखता है, अधिकारी मंज़ूरी देता है, और हर फ़ोन पर हिंदी में चेतावनी सुनाई देती है।',
        },
      },
    ],
  },
  {
    route: '/live',
    targets: [
      {
        sel: '[data-tour="live-map"]',
        title: { en: 'Every village, every 15 minutes', hi: 'हर गाँव, हर 15 मिनट' },
        body: {
          en: 'Each marker is a village, coloured and labelled by its risk level, worked out again from fresh forecasts every 15 minutes. Tap one to see why.',
          hi: 'हर निशान एक गाँव है, उसके ख़तरे के स्तर के रंग और नाम के साथ। हर 15 मिनट नए पूर्वानुमान से दोबारा तय होता है। वजह देखने के लिए किसी पर टैप करें।',
        },
      },
    ],
  },
  {
    route: '/live',
    targets: [
      {
        sel: '[data-tour="funnel"]',
        title: { en: 'From draft to “मिल गया”', hi: 'मसौदे से “मिल गया” तक' },
        body: {
          en: 'Every alert is counted: drafted, approved by an officer, delivered to a phone, and confirmed when someone taps “मिल गया”.',
          hi: 'हर चेतावनी गिनी जाती है: मसौदा बना, अधिकारी ने मंज़ूर किया, फ़ोन तक पहुँची, और किसी ने “मिल गया” दबाकर पुष्टि की।',
        },
      },
    ],
  },
  {
    route: '/village/gohar',
    targets: [
      {
        sel: '[data-tour="why"]',
        title: { en: 'Why this level', hi: 'यह स्तर क्यों' },
        body: {
          en: 'Code sets the level: rain, river, gauge, reports. Each card shows the reading and the line it is measured against. The model never decides.',
          hi: 'स्तर कोड तय करता है: बारिश, नदी, गेज और गाँव की सूचनाएँ। हर कार्ड में माप और उसकी सीमा दिखती है। मॉडल कभी फ़ैसला नहीं करता।',
        },
      },
    ],
  },
  {
    route: '/village/gohar',
    targets: [
      {
        sel: '[data-tour="tte"]',
        title: { en: 'Time to ear', hi: 'कान तक का समय' },
        body: {
          en: 'A stopwatch from the level rising to the first spoken alert on a phone and the first “मिल गया”. Every mark is a recorded timestamp.',
          hi: 'स्तर बढ़ने से फ़ोन पर पहली बोली गई चेतावनी और पहले “मिल गया” तक की घड़ी। हर निशान एक दर्ज समय है।',
        },
      },
      {
        sel: '[data-tour="village-alerts"]',
        title: { en: 'Every alert, on the record', hi: 'हर चेतावनी, दर्ज' },
        body: {
          en: 'Each alert keeps the Hindi text people heard, the officer’s decision, and which phones confirmed it. No alerts here means the village stayed calm.',
          hi: 'हर चेतावनी में लोगों ने जो हिंदी पाठ सुना, अधिकारी का फ़ैसला, और किन फ़ोनों ने पुष्टि की, सब दर्ज रहता है। कोई चेतावनी नहीं, तो गाँव शांत रहा।',
        },
      },
    ],
  },
  {
    route: '/how',
    targets: [
      {
        sel: '[data-tour="how-loop"]',
        title: { en: 'Each step, and why it works', hi: 'हर क़दम, और वह क्यों काम करता है' },
        body: {
          en: 'Seven steps from a forecast to a confirmed alert, each with the AWS service behind it and the research that backs it.',
          hi: 'पूर्वानुमान से पुष्टि हुई चेतावनी तक सात क़दम, हर एक के पीछे की AWS सेवा और उसे सही ठहराने वाला शोध।',
        },
      },
    ],
  },
  {
    route: '/impact',
    targets: [
      {
        sel: '[data-tour="scores"]',
        title: { en: 'Scored against real floods, honestly', hi: 'असली बाढ़ों पर जाँचा, ईमानदारी से' },
        body: {
          en: 'The same rules, replayed over past Mandi floods. Hits, misses and false alarms are all counted, caveats included.',
          hi: 'वही नियम, मंडी की पिछली बाढ़ों पर दोबारा चलाए गए। सही चेतावनी, चूक और झूठी चेतावनी, सब गिने गए हैं, सीमाओं के साथ।',
        },
      },
    ],
  },
  { targets: [] },
];

export const TOUR_LENGTH = TOUR_STEPS.length;
export const END_TEXT: { title: Txt; body: Txt } = {
  title: { en: 'That is the whole loop', hi: 'यही है पूरा चक्र' },
  body: {
    en: 'Watch the villages live, send a report from any phone, or read the code.',
    hi: 'गाँवों को लाइव देखें, किसी भी फ़ोन से सूचना भेजें, या कोड पढ़ें।',
  },
};

/* ---------- store ---------- */

export const TOUR_KEY = 'pukaar.tour';

function readSeen(): boolean {
  try {
    return localStorage.getItem(TOUR_KEY) === 'done';
  } catch {
    return false;
  }
}

function writeSeen() {
  try {
    localStorage.setItem(TOUR_KEY, 'done');
  } catch {
    /* storage blocked: the tour just does not remember */
  }
}

interface TourState {
  active: boolean;
  step: number;
  /** Direction of travel, so a step whose target is missing is skipped the same way. */
  dir: 1 | -1;
  seen: boolean;
  start: () => void;
  next: () => void;
  back: () => void;
  /** A step whose target never appeared: move on in the same direction, or stop at either end. */
  skipMissing: () => void;
  /** Finished or skipped: close and remember it. */
  close: () => void;
}

export const useTour = create<TourState>((set, get) => ({
  active: false,
  step: 0,
  dir: 1,
  seen: readSeen(),
  start: () => {
    // The landing intro would cover the first step.
    writeSession('pukaar.intro', '1');
    set({ active: true, step: 0, dir: 1 });
  },
  next: () => {
    const { active, step } = get();
    if (!active) return;
    if (step >= TOUR_LENGTH - 1) get().close();
    else set({ step: step + 1, dir: 1 });
  },
  back: () => {
    const { active, step } = get();
    if (!active || step === 0) return;
    set({ step: step - 1, dir: -1 });
  },
  skipMissing: () => {
    const { active, step, dir } = get();
    if (!active) return;
    const to = step + dir;
    if (to < 0) set({ step: step + 1, dir: 1 });
    else if (to >= TOUR_LENGTH) get().close();
    else set({ step: to });
  },
  close: () => {
    writeSeen();
    set({ active: false, step: 0, dir: 1, seen: true });
  },
}));

/* ---------- layout ---------- */

export interface Box {
  top: number;
  left: number;
  width: number;
  height: number;
}

export const RING_PAD = 8;
const GAP = 16;
const EDGE = 16;

/**
 * Where the popover goes for a target (viewport coordinates): below if it fits, then above,
 * then beside, else pinned to the bottom of the viewport over the target. `top0` is the
 * height of the sticky header.
 */
export function placePopover(
  target: Box | null,
  pop: { width: number; height: number },
  vp: { width: number; height: number },
  top0: number,
): { top: number; left: number; side: 'below' | 'above' | 'right' | 'left' | 'over' | 'center' } {
  const clampX = (x: number) => Math.max(EDGE, Math.min(x, vp.width - pop.width - EDGE));
  const clampY = (y: number) => Math.max(top0 + EDGE, Math.min(y, vp.height - pop.height - EDGE));
  if (!target) {
    return { top: clampY((vp.height - pop.height) / 2), left: clampX((vp.width - pop.width) / 2), side: 'center' };
  }
  const ring = { top: target.top - RING_PAD, bottom: target.top + target.height + RING_PAD, left: target.left - RING_PAD, right: target.left + target.width + RING_PAD };
  if (vp.height - ring.bottom >= pop.height + GAP + EDGE) {
    return { top: ring.bottom + GAP, left: clampX(ring.left), side: 'below' };
  }
  if (ring.top - top0 >= pop.height + GAP + EDGE) {
    return { top: ring.top - GAP - pop.height, left: clampX(ring.left), side: 'above' };
  }
  if (vp.width - ring.right >= pop.width + GAP + EDGE) {
    return { top: clampY(ring.top), left: ring.right + GAP, side: 'right' };
  }
  if (ring.left >= pop.width + GAP + EDGE) {
    return { top: clampY(ring.top), left: ring.left - GAP - pop.width, side: 'left' };
  }
  return { top: vp.height - pop.height - EDGE, left: clampX(vp.width - pop.width - EDGE), side: 'over' };
}

/**
 * The scroll position that frames a target under the sticky header: the target plus room
 * for the popover centred if both fit, else the target alone centred, else its top just
 * under the header. `reserve` is the height kept free for the popover (or a bottom sheet).
 */
export function scrollTargetY(target: { top: number; height: number }, scrollY: number, vpHeight: number, top0: number, reserve: number): number {
  const docTop = target.top + scrollY;
  const room = vpHeight - top0;
  const h = target.height + RING_PAD * 2;
  let offset: number;
  if (h + reserve + GAP <= room) offset = top0 + (room - h - reserve - GAP) / 2;
  else if (h <= room - EDGE * 2) offset = top0 + (room - h) / 2;
  else offset = top0 + EDGE;
  return Math.max(0, Math.round(docTop - offset - RING_PAD));
}
