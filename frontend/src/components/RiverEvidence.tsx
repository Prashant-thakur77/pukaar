import { Landmark, Waves } from 'lucide-react';
import { useT } from '../i18n';
import { fmtTime } from '../lib/format';
import { cms, cutoffNote, ensembleLines, ensembleNote, officialRows, thresholdRows } from '../lib/riverEvidence';
import type { OfficialItem, RiverView } from '../types';
import { Reveal } from './Reveal';

/**
 * The river's evidence as a ledger: what the forecast runs say against the 2-, 5- and 20-year
 * flood levels, the lines themselves with the get-ready line, and the official sources.
 * Words and hairlines; the numbers are the API's.
 */
export function RiverOdds({ river, official, delay = 90 }: { river: RiverView | null | undefined; official?: OfficialItem[] | null; delay?: number }) {
  const { t, lang } = useT();
  const th = river?.thresholds ?? null;
  const odds = ensembleLines(river, th, lang);
  const note = ensembleNote(river, th, lang);
  const rows = thresholdRows(th, lang);
  const sources = officialRows(official, lang);
  return (
    <Reveal className="ev-card ev-wide rv-card" delay={delay}>
      <header className="ev-head">
        <Waves aria-hidden="true" />
        <h3>{t('river.odds.title')}</h3>
      </header>

      <section className="rv-sec" aria-labelledby="rv-runs-h">
        <h4 id="rv-runs-h" className="rv-k">
          {river?.mode === 'ensemble' ? t('river.runs', { n: river.members ?? 0 }) : t('river.runs.none')}
        </h4>
        {odds.length > 0 && (
          <ul className="rv-odds">
            {odds.map((l) => (
              <li key={l.level} className={l.raises ? `lv-${l.level} is-raising` : undefined}>
                <span>{l.text}</span>
                {l.raises && <span className="rv-flag">{t('river.raises')}</span>}
              </li>
            ))}
          </ul>
        )}
        {note && <p className="rv-note">{note}</p>}
        {river?.mode === 'ensemble' && <p className="small muted">{cutoffNote(river.p_min, lang)}</p>}
      </section>

      {rows.length > 0 && (
        <section className="rv-sec" aria-labelledby="rv-lines-h">
          <h4 id="rv-lines-h" className="rv-k">
            {t('river.lines')}
          </h4>
          <dl className="rv-lines">
            {rows.map((r) => (
              <div key={r.key} className={r.key === 'early' ? 'rv-early' : `lv-${r.key}`}>
                <dt>{r.label}</dt>
                <dd>
                  <span className="rv-what">{r.what}</span>
                  <span className="rv-val">{cms(r.value, lang)} m³/s</span>
                </dd>
              </div>
            ))}
          </dl>
          {(river?.today != null || river?.peak != null) && (
            <p className="meta-line rv-now">
              {river?.today != null && <span>{t('river.today', { v: cms(river.today, lang) })}</span>}
              {river?.peak != null && <span>{t('river.peak3', { v: cms(river.peak, lang) })}</span>}
            </p>
          )}
          {th?.river && (
            <p className="small muted">
              {th.river} · {th.cell_verified ? t('river.cell.checked') : t('river.cell.unchecked')}
            </p>
          )}
        </section>
      )}

      <section className="rv-sec" aria-labelledby="rv-off-h">
        <h4 id="rv-off-h" className="rv-k">
          <Landmark aria-hidden="true" /> {t('river.official')}
        </h4>
        {sources.length === 0 ? (
          <p className="rv-note">{t('river.official.none')}</p>
        ) : (
          <dl className="rv-ledger">
            {sources.map((s) => (
              <div key={s.source} className={s.status !== 'ok' ? 'is-quiet' : s.level ? `lv-${s.level}` : undefined}>
                <dt>{s.label}</dt>
                <dd>{s.text}</dd>
              </div>
            ))}
          </dl>
        )}
        <p className="small muted">{t('river.official.never')}</p>
      </section>
      {river?.at && <p className="ev-sweep small">{t('village.ev.latest', { t: fmtTime(river.at, lang) })}</p>}
    </Reveal>
  );
}
