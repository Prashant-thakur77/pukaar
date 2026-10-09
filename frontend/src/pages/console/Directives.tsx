import { useState, type FormEvent } from 'react';
import { LoaderCircle, Megaphone } from 'lucide-react';
import { api, ApiError } from '../../api';
import { DeniedNote, ErrorState } from '../../components/States';
import type { PollState } from '../../hooks/usePoll';
import { enumLabels, useT } from '../../i18n';
import { fmtAgo } from '../../lib/format';
import type { Directive, DirectiveType, Village } from '../../types';

const TYPES: DirectiveType[] = ['evacuate', 'shelter_in_place', 'advisory', 'all_clear'];

export function Directives({ villages, poll }: { villages: Village[]; poll: PollState<Directive[]> }) {
  const { t, lang, pick } = useT();
  const [villageId, setVillageId] = useState('');
  const [type, setType] = useState<DirectiveType>('advisory');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [done, setDone] = useState<Directive | null>(null);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!villageId) return;
    setBusy(true);
    setErr(null);
    setDone(null);
    try {
      const d = await api.createDirective({ village_id: villageId, type, note_en: note.trim() || undefined });
      setDone(d);
      setNote('');
      void poll.refresh();
    } catch (er) {
      setErr(er instanceof ApiError ? er : new ApiError(0, null));
    } finally {
      setBusy(false);
    }
  }

  const active = (poll.data ?? []).filter((d) => d.active);
  const vname = (id: string) => {
    const v = villages.find((x) => x.id === id);
    return v ? (lang === 'hi' ? v.name_hi : v.name) : id;
  };

  return (
    <div className="directives">
      <form className="stack" onSubmit={submit}>
        <label className="field">
          <span className="field-label">{t('console.directive.village')}</span>
          <span className="select-wrap">
            <select value={villageId} onChange={(e) => setVillageId(e.target.value)} required>
              <option value="">—</option>
              {villages.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.name} · {v.name_hi}
                </option>
              ))}
            </select>
          </span>
        </label>
        <fieldset className="field">
          <legend className="field-label">{t('console.directive.type')}</legend>
          <div className="seg">
            {TYPES.map((ty) => (
              <label key={ty} className={`seg-opt${type === ty ? ' is-on' : ''} dt-${ty}`}>
                <input type="radio" name="dtype" value={ty} checked={type === ty} onChange={() => setType(ty)} />
                {pick(enumLabels.directiveType[ty])}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="field">
          <span className="field-label">{t('console.directive.note')}</span>
          <input value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} />
        </label>
        <button type="submit" className="btn btn-ink btn-press" disabled={busy || !villageId}>
          {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <Megaphone aria-hidden="true" />} {t('console.directive.send')}
        </button>
      </form>
      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
      {done && (
        <p className="ok-text" role="status">
          {t('console.directive.done')}: <span lang="hi">{done.text_hi}</span>
        </p>
      )}
      {active.length > 0 && (
        <>
          <h3 className="h-sub">{t('console.directive.active')}</h3>
          <ul className="directive-list">
            {active.map((d) => (
              <li key={d.id} className={`directive-card dt-${d.type}`}>
                <p className="dc-top">
                  <strong>{pick(enumLabels.directiveType[d.type])}</strong> · {vname(d.village_id)}
                </p>
                <p lang="hi">{d.text_hi}</p>
                <p className="small muted">
                  {d.issued_by} · {fmtAgo(d.issued_at, lang)}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
