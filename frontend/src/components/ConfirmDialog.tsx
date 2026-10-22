import { useEffect, useId, useRef, type ReactNode } from 'react';

interface Props {
  open: boolean;
  title: string;
  children?: ReactNode;
  confirmLabel: string;
  cancelLabel: string;
  tone?: 'accent' | 'danger';
  busy?: boolean;
  /** Short bottom sheet on phones (the one-tap approval page). */
  sheet?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Native <dialog>: focus trap, Esc to close, and backdrop for free. */
export function ConfirmDialog({ open, title, children, confirmLabel, cancelLabel, tone = 'accent', busy, sheet, onConfirm, onCancel }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  // Several cards can each hold a dialog: every title needs its own id.
  const titleId = useId();
  const danger = tone === 'danger';
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal?.();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className={`dialog${sheet ? ' is-sheet' : ''}`} onCancel={(e) => { e.preventDefault(); onCancel(); }} aria-labelledby={titleId}>
      <h2 id={titleId} className="dialog-title">{title}</h2>
      <div className="dialog-body">{children}</div>
      <div className="dialog-actions">
        {/* A destructive action never takes the focus: Enter on a sleepy tap keeps things as they are. */}
        <button type="button" className="btn btn-ghost" onClick={onCancel} autoFocus={danger}>
          {cancelLabel}
        </button>
        <button type="button" className={`btn ${danger ? 'btn-danger' : 'btn-accent'}`} onClick={onConfirm} disabled={busy} autoFocus={!danger}>
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
