import { useEffect, useRef, type ReactNode } from 'react';

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
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal?.();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className={`dialog${sheet ? ' is-sheet' : ''}`} onCancel={(e) => { e.preventDefault(); onCancel(); }} aria-labelledby="dlg-title">
      <h2 id="dlg-title" className="dialog-title">{title}</h2>
      <div className="dialog-body">{children}</div>
      <div className="dialog-actions">
        <button type="button" className="btn btn-ghost" onClick={onCancel}>
          {cancelLabel}
        </button>
        <button type="button" className={`btn ${tone === 'danger' ? 'btn-danger' : 'btn-accent'}`} onClick={onConfirm} disabled={busy} autoFocus>
          {confirmLabel}
        </button>
      </div>
    </dialog>
  );
}
