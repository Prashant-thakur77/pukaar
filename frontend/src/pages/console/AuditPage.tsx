import { useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { ChevronRight, Copy, Download, ShieldCheck, ShieldX, X } from 'lucide-react';
import { api } from '../../api';
import { ErrorState, Skeleton } from '../../components/States';
import { usePoll } from '../../hooks/usePoll';
import { useMedia } from '../../hooks/useMedia';
import { useT } from '../../i18n';
import { istClock } from '../../lib/answerText';
import { actionWords, applyFilters, auditCsv, AUDIT_KINDS, groupReads, readFilters, villageOf, writeFilters, type AuditFilters, type AuditLine } from '../../lib/audit';
import type { Lang } from '../../store';
import { useConsole } from './consoleContext';
import { Page } from './Sections';

/*
 * The audit trail (spec 4.11, C27). Today's changes and decisions first; the officer's own page views hidden and,
 * when shown, folded ("judge viewed the roster ×14 · 19:44–23:10"). Filters live in the URL. A row opens the full
 * record with the policy's reason and a JSON copy. 50 rows at a time; the CSV holds exactly what is shown.
 */

const PAGE = 50;
// The trail is kept by UTC day (api/routers/officer.py /audit); the picker says so.
const todayUTC = () => new Date().toISOString().slice(0, 10);

export default function AuditPage() {
  const { t, lang } = useT();
  const c = useConsole();
  const [params, setParams] = useSearchParams();
  const f = readFilters(params);
  const date = params.get('date') ?? '';
  const day = date || todayUTC();
  const { data, error, loading, refresh } = usePoll(() => api.audit({ date: day }), [day], 30000);
  const [shown, setShown] = useState(PAGE);
  const [open, setOpen] = useState<string | null>(null);
  const wide = useMedia('(min-width: 1024px)');

  const alertVillage = useMemo(() => {
    const m = new Map((c.alerts.data ?? []).map((a) => [a.id, a.village_id]));
    return (id: string) => m.get(id);
  }, [c.alerts.data]);
  const rows = data ?? [];
  const { rows: kept, hiddenReads } = applyFilters(rows, f, alertVillage);
  const lines = groupReads(kept);
  const visible = lines.slice(0, shown);
  const people = [...new Set(rows.map((r) => r.actor))].sort();
  const set = (patch: Partial<AuditFilters>, nextDate = date) => {
    setShown(PAGE);
    setOpen(null);
    setParams(writeFilters({ ...f, ...patch }, nextDate), { replace: true });
  };
  const selected = lines.find((l) => l.key === open) ?? null;

  const download = () => {
    const blob = new Blob([auditCsv(kept)], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `pukaar-audit-${day}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30_000);
  };

  return (
    <Page title={t('audit.title')} lead={t('audit.lead')} wide>
      <div className="au-tools" role="search">
        <div className="seg" role="group" aria-label={t('aud.changes')}>
          <button type="button" className={`seg-btn${!f.all ? ' is-on' : ''}`} aria-pressed={!f.all} onClick={() => set({ all: false })}>
            {t('aud.changes')}
          </button>
          <button type="button" className={`seg-btn${f.all ? ' is-on' : ''}`} aria-pressed={f.all} onClick={() => set({ all: true })}>
            {t('aud.everything')}
          </button>
        </div>
        <label className="au-field">
          <span>{t('aud.type')}</span>
          <select value={f.kind} onChange={(e) => set({ kind: e.target.value as AuditFilters['kind'] })}>
            <option value="">{t('aud.type.all')}</option>
            {AUDIT_KINDS.map((k) => (
              <option key={k} value={k}>
                {t(`aud.type.${k}`)}
              </option>
            ))}
            <option value="denied">{t('aud.type.denied')}</option>
          </select>
        </label>
        <label className="au-field">
          <span>{t('aud.village')}</span>
          <select value={f.village} onChange={(e) => set({ village: e.target.value })}>
            <option value="">{t('aud.anywhere')}</option>
            {(c.villages.data ?? []).map((v) => (
              <option key={v.id} value={v.id}>
                {lang === 'hi' ? v.name_hi : v.name}
              </option>
            ))}
          </select>
        </label>
        <label className="au-field">
          <span>{t('aud.person')}</span>
          <select value={f.person} onChange={(e) => set({ person: e.target.value })}>
            <option value="">{t('aud.anyone')}</option>
            {people.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </label>
        <label className="au-field">
          <span>{t('aud.date')}</span>
          <input type="date" value={day} max={todayUTC()} onChange={(e) => set({}, e.target.value)} />
        </label>
      </div>

      {data && (
      <div className="au-bar">
        <p className="au-count" role="status">
          {f.all ? t('aud.count.all', { n: kept.length }) : t('aud.count', { n: kept.length, r: hiddenReads })}
          {f.q && (
            <>
              {' · '}
              <code>{f.q}</code>
            </>
          )}
        </p>
        <span className="au-bar-tools">
          {(f.kind || f.village || f.person || f.q || f.all || date) && (
            <button type="button" className="btn btn-sm btn-ghost" onClick={() => setParams({}, { replace: true })}>
              {t('aud.reset')}
            </button>
          )}
          <button type="button" className="btn btn-sm btn-ghost" onClick={download} disabled={!kept.length}>
            <Download aria-hidden="true" /> {t('aud.csv')}
          </button>
        </span>
      </div>
      )}

      {loading && !data ? (
        <Skeleton lines={8} />
      ) : error && !data ? (
        <ErrorState error={error} onRetry={refresh} />
      ) : !lines.length ? (
        <div className="ib-empty">
          <p className="ib-empty-title">{t('aud.none')}</p>
          <p className="ib-empty-body">{t('aud.none.body')}</p>
        </div>
      ) : (
        <div className={`au-wrap${selected && wide ? ' has-panel' : ''}`}>
          <ol className="au-list">
            {visible.map((l) => (
              <li key={l.key}>
                <AuditRow line={l} lang={lang} villageName={(id) => (c.villages.data ?? []).find((v) => v.id === id)} alertVillage={alertVillage} open={open === l.key} onToggle={() => setOpen(open === l.key ? null : l.key)} />
                {open === l.key && !wide && <AuditDetail line={l} onClose={() => setOpen(null)} />}
              </li>
            ))}
          </ol>
          {selected && wide && <AuditDetail line={selected} onClose={() => setOpen(null)} side />}
        </div>
      )}
      {lines.length > shown && (
        <button type="button" className="btn btn-ghost au-more" onClick={() => setShown((n) => n + PAGE)}>
          {t('aud.more', { n: lines.length - shown })}
        </button>
      )}
    </Page>
  );
}

function AuditRow({
  line,
  lang,
  villageName,
  alertVillage,
  open,
  onToggle,
}: {
  line: AuditLine;
  lang: Lang;
  villageName: (id: string) => { name: string; name_hi: string } | undefined;
  alertVillage: (id: string) => string | undefined;
  open: boolean;
  onToggle: () => void;
}) {
  const { t } = useT();
  const r = line.row;
  const vid = villageOf(r, alertVillage);
  const v = vid ? villageName(vid) : undefined;
  // The whole service ("app:pukaar", "village:pukaar") names no place: say nothing rather than a code.
  const where = v ? (lang === 'hi' ? v.name_hi : v.name) : /:pukaar$/.test(r.resource) ? null : r.resource;
  const deny = r.decision === 'deny';
  return (
    <button type="button" className={`au-row${deny ? ' is-deny' : ''}${open ? ' is-open' : ''}`} aria-expanded={open} onClick={onToggle}>
      <span className="au-time">{istClock(r.at)?.replace(' IST', '')}</span>
      <span className="au-who">
        {r.actor} <span className="au-role">({r.role})</span>
      </span>
      <span className="au-what">
        {actionWords(r.action, lang)}
        {line.count > 1 && (
          <span className="au-times">
            {' '}
            {t('aud.times', { n: line.count, from: istClock(line.from)?.replace(' IST', '') ?? '', to: istClock(line.to)?.replace(' IST', '') ?? '' })}
          </span>
        )}
      </span>
      <span className="au-where">{where}</span>
      <span className={`au-dec${deny ? ' is-deny' : ''}`}>
        {deny ? <ShieldX aria-hidden="true" /> : <ShieldCheck aria-hidden="true" />}
        <span className={deny ? '' : 'sr-only'}>{deny ? t('aud.denied') : t('aud.allowed')}</span>
      </span>
      <ChevronRight aria-hidden="true" className="au-go" />
    </button>
  );
}

function AuditDetail({ line, onClose, side = false }: { line: AuditLine; onClose: () => void; side?: boolean }) {
  const { t, lang } = useT();
  const r = line.row;
  const [copied, setCopied] = useState(false);
  const json = JSON.stringify(line.count > 1 ? line.rows : r, null, 2);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };
  return (
    <aside className={`au-detail${side ? ' is-side' : ''}`} aria-label={t('aud.record')}>
      {side && (
        <div className="au-detail-head">
          <h2 className="au-detail-h">{actionWords(r.action, lang)}</h2>
          <button type="button" className="hd-icon" onClick={onClose} aria-label={t('aud.close')}>
            <X aria-hidden="true" />
          </button>
        </div>
      )}
      <dl className="au-dl">
        <div>
          <dt>{t('aud.when')}</dt>
          <dd>{line.count > 1 ? `${istClock(line.from)} – ${istClock(line.to)} · ×${line.count}` : `${istClock(r.at)} · ${r.at.slice(0, 10)}`}</dd>
        </div>
        <div>
          <dt>{t('aud.person')}</dt>
          <dd>
            {r.actor} ({r.role})
          </dd>
        </div>
        <div>
          <dt>{t('aud.resource')}</dt>
          <dd>
            <code>{r.resource}</code> · <code>{r.action}</code>
          </dd>
        </div>
        <div>
          <dt>{t('aud.why')}</dt>
          <dd className={r.decision === 'deny' ? 'bad-text' : ''}>
            {r.decision === 'deny' ? t('aud.denied') : t('aud.allowed')}: {r.reason}
          </dd>
        </div>
      </dl>
      <details className="au-json">
        <summary>{t('aud.record')}</summary>
        <pre>{json}</pre>
      </details>
      <button type="button" className="btn btn-sm btn-ghost" onClick={() => void copy()}>
        <Copy aria-hidden="true" /> {copied ? t('aud.copied') : t('aud.copy')}
      </button>
    </aside>
  );
}
