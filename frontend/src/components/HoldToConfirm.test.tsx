import { act, createRef } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { HOLD_MS, HoldToConfirm, type HoldHandle } from './HoldToConfirm';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const TEXT = {
  idle: 'Hold to approve and send',
  holding: 'Keep holding…',
  almost: 'Don’t let go…',
  sending: 'Sending',
  done: 'Approved',
  hint: 'Hold for 1 second',
  confirmQ: 'Sure? Enter to send · Esc to cancel',
  confirmYes: 'Yes, send',
  confirmNo: 'Cancel',
};

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.useFakeTimers();
  host = document.createElement('div');
  document.body.appendChild(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.useRealTimers();
});

const btn = () => host.querySelector('.hold-btn') as HTMLButtonElement;
const pointer = (type: string) => btn().dispatchEvent(new MouseEvent(type, { bubbles: true, button: 0 }));

describe('hold to approve (S4)', () => {
  it('sends once after a full second of holding, and says so as it fills', async () => {
    const onConfirm = vi.fn(() => Promise.resolve());
    act(() => root.render(<HoldToConfirm text={TEXT} onConfirm={onConfirm} />));
    expect(btn().textContent).toContain(TEXT.idle);
    act(() => pointer('pointerdown'));
    expect(btn().className).toContain('is-holding');
    act(() => vi.advanceTimersByTime(HOLD_MS * 0.7));
    expect(btn().textContent).toContain(TEXT.almost);
    expect(onConfirm).not.toHaveBeenCalled();
    await act(async () => {
      vi.advanceTimersByTime(HOLD_MS * 0.4);
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
    expect(btn().textContent).toContain(TEXT.done);
    // A second hold does nothing: the request went once.
    act(() => pointer('pointerdown'));
    act(() => vi.advanceTimersByTime(HOLD_MS * 2));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('snaps back when let go early', () => {
    const onConfirm = vi.fn(() => Promise.resolve());
    act(() => root.render(<HoldToConfirm text={TEXT} onConfirm={onConfirm} />));
    act(() => pointer('pointerdown'));
    act(() => vi.advanceTimersByTime(HOLD_MS / 2));
    act(() => pointer('pointerup'));
    act(() => vi.advanceTimersByTime(HOLD_MS * 2));
    expect(onConfirm).not.toHaveBeenCalled();
    expect(btn().className).toContain('is-idle');
  });

  it('a key tap opens the confirm row, which sends; Escape cancels it', async () => {
    const onConfirm = vi.fn(() => Promise.resolve());
    const ref = createRef<HoldHandle>();
    act(() => root.render(<HoldToConfirm ref={ref} text={TEXT} onConfirm={onConfirm} />));
    act(() => ref.current?.begin());
    act(() => ref.current?.end());
    const group = host.querySelector('.hold-confirm') as HTMLElement;
    expect(group.getAttribute('aria-label')).toBe(TEXT.confirmQ);
    act(() => group.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })));
    expect(host.querySelector('.hold-confirm')).toBeNull();
    expect(onConfirm).not.toHaveBeenCalled();
    act(() => ref.current?.confirm());
    await act(async () => {
      (host.querySelector('.hold-confirm .btn-approve') as HTMLButtonElement).click();
    });
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it('tells assistive technology how it works', () => {
    act(() => root.render(<HoldToConfirm text={TEXT} onConfirm={() => Promise.resolve()} />));
    const id = btn().getAttribute('aria-describedby');
    expect(id && document.getElementById(id)?.textContent).toBe(TEXT.hint);
  });
});
