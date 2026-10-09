import { useEffect } from 'react';
import { Undo2, X } from 'lucide-react';

export interface SnackbarMsg {
  id: number;
  text: string;
  actionLabel?: string;
  onAction?: () => void;
}

export function Snackbar({ msg, onClose, closeLabel }: { msg: SnackbarMsg | null; onClose: () => void; closeLabel: string }) {
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(onClose, 7000);
    return () => clearTimeout(t);
  }, [msg, onClose]);
  return (
    <div className="snackbar-host" aria-live="polite">
      {msg && (
        <div className="snackbar" key={msg.id} role="status">
          <span>{msg.text}</span>
          {msg.onAction && (
            <button
              type="button"
              className="btn btn-sm btn-accent"
              onClick={() => {
                msg.onAction?.();
                onClose();
              }}
            >
              <Undo2 aria-hidden="true" /> {msg.actionLabel}
            </button>
          )}
          <button type="button" className="icon-btn" onClick={onClose} aria-label={closeLabel}>
            <X aria-hidden="true" />
          </button>
        </div>
      )}
    </div>
  );
}
