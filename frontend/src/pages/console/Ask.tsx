import { useMemo, useState, type FormEvent } from 'react';
import { Bot, ChevronDown, LoaderCircle, Send, ShieldCheck, ShieldX, Wrench } from 'lucide-react';
import { api, ApiError } from '../../api';
import { Chart } from '../../components/Chart';
import { dict, useT, type Key } from '../../i18n';
import { DeniedNote, ErrorState } from '../../components/States';
import { VillageMap } from '../../components/VillageMap';
import { levelsFromTools } from '../../lib/ask';
import type { AskResponse, Village } from '../../types';

const SUGGEST: Key[] = ['console.ask.q1', 'console.ask.q2', 'console.ask.q3'];

function preview(v: unknown): string {
  try {
    const s = typeof v === 'string' ? v : JSON.stringify(v);
    return s.length > 160 ? `${s.slice(0, 157)}…` : s;
  } catch {
    return String(v);
  }
}

export function Ask({ villages }: { villages: Village[] }) {
  const { t, lang } = useT();
  const [q, setQ] = useState('');
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<AskResponse | null>(null);
  const [asked, setAsked] = useState('');
  const [err, setErr] = useState<ApiError | null>(null);
  const [traceOpen, setTraceOpen] = useState(false);

  async function ask(question: string) {
    if (!question.trim()) return;
    setBusy(true);
    setErr(null);
    setAsked(question);
    try {
      setRes(await api.ask(question.trim()));
      setTraceOpen(false);
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
      setRes(null);
    } finally {
      setBusy(false);
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void ask(q);
  };

  // Levels on the map come from the answer's own tool output when it has them,
  // so the map never contradicts the text; otherwise it says "current levels".
  const toolLevels = useMemo(() => levelsFromTools(res?.tools), [res]);
  const fromAnswer = Object.keys(toolLevels).length > 0;
  const mapVillages = useMemo(
    () =>
      res?.map
        ? villages
            .filter((v) => res.map!.village_ids.includes(v.id) || villages.length <= 12)
            .map((v) => (toolLevels[v.id] ? { ...v, level: toolLevels[v.id] } : v))
        : [],
    [res, villages, toolLevels],
  );
  // Chart bars are villages (by name or id): colour each by the level the answer used.
  const levelOf = useMemo(() => {
    const m = new Map<string, Village['level']>();
    for (const v of villages) {
      const lv = toolLevels[v.id] ?? v.level;
      for (const k of [v.id, v.name, v.name_hi]) if (k) m.set(k.toLowerCase(), lv);
    }
    return (x: string) => m.get(x.toLowerCase());
  }, [villages, toolLevels]);

  // Points that are villages already have a marker; only extra places get a pin.
  const extraPoints = useMemo(() => {
    if (!res?.map) return [];
    const names = new Set(villages.flatMap((v) => [v.name.toLowerCase(), v.name_hi]));
    return res.map.points.filter((p) => !names.has(p.label.toLowerCase()) && !names.has(p.label));
  }, [res, villages]);

  return (
    <div className="ask">
      <p className="small muted">{t('console.ask.lead')}</p>
      <form className="ask-form" onSubmit={submit}>
        <label className="sr-only" htmlFor="ask-q">
          {t('console.ask')}
        </label>
        <textarea id="ask-q" rows={2} value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('console.ask.placeholder')} onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            void ask(q);
          }
        }} />
        <button type="submit" className="btn btn-accent btn-press" disabled={busy || !q.trim()}>
          {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <Send aria-hidden="true" />} {t('console.ask.send')}
        </button>
      </form>
      <div className="suggest">
        {SUGGEST.map((k) => (
          <button key={k} type="button" className="chip chip-btn" onClick={() => {
            setQ(t(k));
            void ask(t(k));
          }} disabled={busy}>
            {t(k)}
          </button>
        ))}
      </div>
      {busy && (
        <div className="ask-thinking" role="status">
          <span className="dots" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span className="small muted">“{asked}”</span>
        </div>
      )}
      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
      {res && !busy && (
        <section className="ask-answer" aria-live="polite">
          <p className="ask-q small muted">“{asked}”</p>
          <p className="ask-text">{res.answer}</p>
          <p className="chip">
            <Bot aria-hidden="true" /> {t('console.ask.model', { m: res.model === 'rule-fallback' ? t('console.model.fallback') : res.model })}
          </p>
          {res.chart && (
            <Chart
              spec={res.chart}
              levelOf={levelOf}
              levelWord={(l) => dict[`level.${l}`][lang]}
              thresholdLabel={t('chart.threshold')}
              note={t('chart.note')}
            />
          )}
          {res.map && (mapVillages.length > 0 || res.map.points.length > 0) && (
            <div className="ask-map">
              <VillageMap
                villages={mapVillages}
                highlight={res.map.village_ids}
                points={extraPoints}
                focus={res.map.village_ids}
                caption={fromAnswer ? t('map.answer') : t('map.current')}
                compact
              />
            </div>
          )}
          {res.tools.length > 0 && (
            <div className="trace">
              <button type="button" className="trace-toggle" aria-expanded={traceOpen} onClick={() => setTraceOpen((o) => !o)}>
                <Wrench aria-hidden="true" /> {t('console.ask.tools', { n: res.tools.length })}
                <ChevronDown aria-hidden="true" className={traceOpen ? 'rot' : ''} />
              </button>
              {traceOpen && (
                <ol className="trace-list">
                  {res.tools.map((tc, i) => (
                    <li key={i} className={`trace-item ${tc.decision === 'deny' ? 'is-deny' : ''}`}>
                      <p className="ti-head">
                        <code>{tc.name}</code>
                        <span className={`chip ${tc.decision === 'deny' ? 'chip-bad' : 'chip-good'}`}>
                          {tc.decision === 'deny' ? <ShieldX aria-hidden="true" /> : <ShieldCheck aria-hidden="true" />} {tc.decision}
                        </span>
                      </p>
                      <p className="small">
                        <span className="muted">input </span>
                        <code className="ti-code">{preview(tc.input)}</code>
                      </p>
                      <p className="small">{tc.output_summary}</p>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
