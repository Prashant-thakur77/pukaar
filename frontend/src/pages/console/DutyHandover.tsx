import { useState } from 'react';
import { ClipboardCheck, NotebookPen, Stethoscope } from 'lucide-react';
import { ApiError } from '../../api';
import { DeniedNote, ErrorState, Skeleton } from '../../components/States';
import { usePoll } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import { istClock } from '../../lib/answerText';
import { reachApi, type HandoverNote } from '../../lib/reach';
import { useConsole } from './consoleContext';
import '../../styles/reach.css';

/*
 * The duty officer's shift (backend services/duty.py), on the roster page:
 *   - the handover: the outgoing officer writes what the next shift must know; an officer of the incoming shift
 *     acknowledges the previous shift's note. Both are in the audit trail, both held to the officer's district;
 *   - this morning's health digest, as it went (or will go) at 08:00 IST on Telegram and Web Push.
 */

export function DutyHandover({ district }: { district: string }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const c = useConsole();
  const poll = usePoll(() => reachApi.handover(district), [district], 60_000);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [saved, setSaved] = useState('');
  if (!district) return null;
  const v = poll.data;

  const act = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setErr(null);
    setSaved('');
    try {
      await fn();
      setSaved(done);
      setText('');
      poll.refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="ho" aria-labelledby="ho-h">
      <h2 id="ho-h" className="dp-sec-h">
        <NotebookPen aria-hidden="true" /> {hi ? `पाली का हैंडओवर · ${district}` : `Shift handover · ${district}`}
      </h2>
      {poll.loading && !v ? (
        <Skeleton lines={3} />
      ) : poll.error && !v ? (
        poll.error.isDenied ? <DeniedNote error={poll.error} /> : <ErrorState error={poll.error} onRetry={poll.refresh} compact />
      ) : v ? (
        <>
          <h3 className="dp-sec-h">{hi ? `पिछली पाली से (${v.previous.label})` : `From the previous shift (${v.previous.label})`}</h3>
          {v.incoming ? (
            <Note note={v.incoming} />
          ) : (
            <p className="dp-meta">{hi ? 'पिछली पाली ने कोई नोट नहीं छोड़ा।' : 'The previous shift left no note.'}</p>
          )}
          {v.incoming && !v.incoming.acknowledged_by && c.officer && (
            <button
              type="button"
              className="btn btn-accent"
              disabled={busy || v.incoming.written_by === c.username}
              onClick={() => void act(() => reachApi.ackHandover(district, v.incoming!.date, v.incoming!.shift), hi ? 'स्वीकार किया।' : 'Acknowledged.')}
            >
              <ClipboardCheck aria-hidden="true" /> {hi ? 'पढ़ लिया, स्वीकार करें' : 'Read: acknowledge'}
            </button>
          )}

          <h3 className="dp-sec-h">{hi ? `अगली पाली के लिए (${v.next.label})` : `For the next shift (${v.next.label})`}</h3>
          {v.outgoing && <Note note={v.outgoing} />}
          {c.officer && !v.outgoing?.acknowledged_by && (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void act(() => reachApi.writeHandover(district, text), hi ? 'नोट सहेजा।' : 'Note saved.');
              }}
            >
              <label className="field" htmlFor="ho-text">
                <span className="field-label">
                  {v.outgoing ? (hi ? 'नोट बदलें' : 'Change the note') : hi ? 'अगली पाली को क्या जानना है' : 'What the next shift must know'}
                </span>
                <textarea id="ho-text" rows={4} maxLength={1000} value={text} onChange={(e) => setText(e.target.value)} />
              </label>
              <button type="submit" className="btn btn-ghost" disabled={busy || !text.trim()}>
                {hi ? 'नोट सहेजें' : 'Save the note'}
              </button>
            </form>
          )}
          {saved && (
            <p className="dp-meta" role="status">
              {saved}
            </p>
          )}
          {err && (err.isDenied ? <DeniedNote error={err} /> : <p className="dp-note is-bad" role="alert">{err.messageIn(hi ? 'hi' : 'en')}</p>)}
        </>
      ) : null}
      <Digest district={district} />
    </section>
  );
}

function Note({ note }: { note: HandoverNote }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  return (
    <>
      <p className="ho-note">{note.text}</p>
      <p className="dp-meta">
        {hi ? `लिखा: ${note.written_by}, ${istClock(note.written_at)} IST` : `Written by ${note.written_by} at ${istClock(note.written_at)} IST`}
        {' · '}
        {note.acknowledged_by
          ? hi
            ? `स्वीकार: ${note.acknowledged_by}, ${istClock(note.acknowledged_at ?? '')} IST`
            : `acknowledged by ${note.acknowledged_by} at ${istClock(note.acknowledged_at ?? '')} IST`
          : hi
            ? 'अभी स्वीकार नहीं'
            : 'not acknowledged yet'}
      </p>
    </>
  );
}

function Digest({ district }: { district: string }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const [open, setOpen] = useState(false);
  const poll = usePoll(() => (open ? reachApi.digest(district) : Promise.resolve(null)), [district, open], 0);
  return (
    <details className="enr-sec" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <Stethoscope aria-hidden="true" /> {hi ? 'सुबह 08:00 की जाँच (टेलीग्राम और वेब पुश)' : 'The 08:00 health digest (Telegram and Web Push)'}
      </summary>
      {open && poll.loading && !poll.data ? (
        <Skeleton lines={3} />
      ) : poll.error ? (
        <ErrorState error={poll.error} compact />
      ) : poll.data ? (
        <p className="ho-digest">{poll.data.text}</p>
      ) : null}
    </details>
  );
}
