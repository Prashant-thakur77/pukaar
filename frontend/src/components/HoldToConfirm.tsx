import { useCallback, useEffect, useId, useImperativeHandle, useRef, useState, type Ref } from 'react';
import { Check, LoaderCircle } from 'lucide-react';
import { useReducedMotion } from '../hooks/useMotion';

/*
 * C12 / S4, hold to approve. The one irreversible action in the console needs a deliberate second step:
 *   - pointer: press and hold for one second while the bar fills; let go early and it snaps back;
 *   - keyboard: hold Enter or Space (or A, from the inbox) the same second; or press once to reveal a confirm
 *     row, "पक्का? Enter से भेजें · Esc रद्द", which is also the screen reader's path;
 *   - reduced motion: no fill, a three-step countdown in words.
 * Once it completes the request goes once: the control stays disabled until the caller's promise settles.
 */

export const HOLD_MS = 1000;
/** A key press shorter than this is a tap: it opens the confirm row instead of holding. */
const TAP_MS = 300;

export interface HoldHandle {
  /** Start holding (a key went down). */
  begin(): void;
  /** The key came up: a tap opens the confirm row, a long hold that did not finish cancels. */
  end(): void;
  /** Show the confirm row and focus its button. */
  confirm(): void;
}

type Phase = 'idle' | 'holding' | 'confirming' | 'sending' | 'done';

export interface HoldText {
  /** At rest: "दबाए रखें: मंज़ूर करें और भेजें". */
  idle: string;
  holding: string;
  /** Past 60 %: "छोड़ें नहीं…". */
  almost: string;
  sending: string;
  done: string;
  /** For assistive technology: "1 सेकंड दबाए रखें". */
  hint: string;
  confirmQ: string;
  confirmYes: string;
  confirmNo: string;
}

interface Props {
  text: HoldText;
  onConfirm: () => Promise<unknown>;
  disabled?: boolean;
  /** Shown as a key hint on the button, e.g. "A". */
  keyHint?: string;
  className?: string;
  ref?: Ref<HoldHandle>;
}

export function HoldToConfirm({ text, onConfirm, disabled = false, keyHint, className = '', ref }: Props) {
  const reduced = useReducedMotion();
  const [phase, setPhase] = useState<Phase>('idle');
  const [almost, setAlmost] = useState(false);
  const [count, setCount] = useState(3);
  const timers = useRef<number[]>([]);
  const startedAt = useRef(0);
  const fired = useRef(false);
  const yesRef = useRef<HTMLButtonElement>(null);
  const btnRef = useRef<HTMLButtonElement>(null);
  const hintId = useId();
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    return () => {
      live.current = false;
      timers.current.forEach(clearTimeout);
    };
  }, []);

  const clear = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  const fire = useCallback(async () => {
    if (fired.current) return;
    fired.current = true;
    clear();
    setPhase('sending');
    navigator.vibrate?.(30);
    try {
      await onConfirm();
      if (live.current) setPhase('done');
    } catch {
      // The caller shows the error; the control is ready for another try.
      if (live.current) {
        fired.current = false;
        setPhase('idle');
      }
    }
  }, [onConfirm]);

  const begin = useCallback(() => {
    if (disabled || fired.current || phase === 'holding' || phase === 'sending' || phase === 'done') return;
    clear();
    startedAt.current = Date.now();
    setAlmost(false);
    setCount(3);
    setPhase('holding');
    timers.current.push(window.setTimeout(() => setAlmost(true), HOLD_MS * 0.6));
    timers.current.push(window.setTimeout(() => setCount(2), HOLD_MS / 3));
    timers.current.push(window.setTimeout(() => setCount(1), (HOLD_MS * 2) / 3));
    timers.current.push(window.setTimeout(() => void fire(), HOLD_MS));
  }, [disabled, phase, fire]);

  const release = useCallback(
    (fromKey: boolean) => {
      if (phase !== 'holding' || fired.current) return;
      clear();
      const tap = Date.now() - startedAt.current < TAP_MS;
      setAlmost(false);
      if (fromKey && tap) {
        setPhase('confirming');
        window.setTimeout(() => yesRef.current?.focus(), 0);
      } else setPhase('idle');
    },
    [phase],
  );

  const showConfirm = useCallback(() => {
    if (disabled || fired.current) return;
    clear();
    setPhase('confirming');
    window.setTimeout(() => yesRef.current?.focus(), 0);
  }, [disabled]);

  useImperativeHandle(ref, () => ({ begin, end: () => release(true), confirm: showConfirm }), [begin, release, showConfirm]);

  const cancelConfirm = () => {
    setPhase('idle');
    btnRef.current?.focus();
  };

  const label =
    phase === 'sending' ? text.sending : phase === 'done' ? text.done : phase === 'holding' ? (reduced ? `${text.holding} ${count}…` : almost ? text.almost : text.holding) : text.idle;
  const busy = phase === 'sending';

  return (
    <div className={`hold ${className}`}>
      <button
        ref={btnRef}
        type="button"
        className={`hold-btn is-${phase}${reduced ? ' is-reduced' : ''}`}
        disabled={disabled || busy || phase === 'done'}
        aria-describedby={hintId}
        onPointerDown={(e) => {
          if (e.button !== 0) return;
          e.currentTarget.setPointerCapture?.(e.pointerId);
          begin();
        }}
        onPointerUp={() => release(false)}
        onPointerCancel={() => release(false)}
        onLostPointerCapture={() => release(false)}
        onKeyDown={(e) => {
          if ((e.key === 'Enter' || e.key === ' ') && !e.repeat) {
            e.preventDefault();
            begin();
          }
        }}
        onKeyUp={(e) => {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            release(true);
          }
        }}
        // A click with no hold (a screen reader's activation) opens the confirm row.
        onClick={(e) => {
          if (e.detail === 0 && phase === 'idle') showConfirm();
        }}
      >
        <span className="hold-fill" aria-hidden="true" />
        <span className="hold-label">
          {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : phase === 'done' ? <Check aria-hidden="true" /> : null}
          <span aria-live="polite">{label}</span>
        </span>
        {keyHint && phase !== 'done' && (
          <kbd className="hold-key" aria-hidden="true">
            {keyHint}
          </kbd>
        )}
      </button>
      <span id={hintId} className="sr-only">
        {text.hint}
      </span>
      {phase === 'confirming' && (
        <div
          className="hold-confirm"
          role="group"
          aria-label={text.confirmQ}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              e.stopPropagation();
              cancelConfirm();
            }
          }}
        >
          <span className="hold-q">{text.confirmQ}</span>
          <button ref={yesRef} type="button" className="btn btn-approve" onClick={() => void fire()}>
            {text.confirmYes}
          </button>
          <button type="button" className="btn btn-ghost" onClick={cancelConfirm}>
            {text.confirmNo}
          </button>
        </div>
      )}
    </div>
  );
}
