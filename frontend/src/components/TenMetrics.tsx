import { api } from '../api';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { fmtTime } from '../lib/format';
import { TEN, dataNow, groupCell, nowCell } from '../lib/pilotTen';
import { ErrorState, Skeleton } from './States';

/*
 * /pilot: the ten pilot metrics (docs/PILOT_PROTOCOL.md), counted by the API from stored records
 * (GET /public/pilot-metrics, "ten"). Live alerts, drills and replays in their own columns; "—" means not
 * measured, and the page says plainly that most are "—" today.
 */
export function TenMetrics() {
  const { lang } = useT();
  const en = lang === 'en';
  const { data, error, loading, refresh } = usePoll(() => api.pilotMetrics(), [], 0);
  if (error && !data) return <ErrorState error={error} onRetry={() => void refresh()} />;
  if (loading && !data) return <Skeleton lines={6} />;
  const t = data?.ten;
  if (!t) return <p className="small muted">{en ? 'Not measured yet.' : 'अभी मापा नहीं।'}</p>;
  const cols = [
    { key: 'live' as const, label: en ? `Live alerts (${t.live.alerts})` : `असली चेतावनियाँ (${t.live.alerts})` },
    { key: 'drill' as const, label: en ? `Drills (${t.drill.alerts})` : `अभ्यास (${t.drill.alerts})` },
    { key: 'replay' as const, label: en ? `Replays (${t.replay.alerts})` : `रीप्ले (${t.replay.alerts})` },
  ];
  return (
    <>
      <p className="pl-facts">
        {en
          ? `Measured from stored records, not estimated. With ${t.live.alerts} real alert${t.live.alerts === 1 ? '' : 's'} so far, most cells are “—”: not measured yet. Drills and replays are counted apart from real alerts; a replay reaches only the demo channel, so it has no reach to measure.`
          : `सहेजे गए रिकॉर्ड से मापा गया, अनुमान नहीं। अब तक ${t.live.alerts} असली चेतावनी, इसलिए ज़्यादातर ख़ाने “—” हैं: अभी मापा नहीं। अभ्यास और रीप्ले असली चेतावनियों से अलग गिने जाते हैं; रीप्ले केवल डेमो चैनल तक जाता है, इसलिए उसकी पहुँच मापी नहीं जाती।`}
      </p>
      <div className="table-wrap pl-table" tabIndex={0} role="region" aria-label={en ? 'The ten pilot metrics' : 'पायलट के दस माप'}>
        <table className="data-table stack-sm">
          <caption className="sr-only">{en ? 'The ten pilot metrics, measured so far' : 'पायलट के दस माप, अब तक'}</caption>
          <thead>
            <tr>
              <th scope="col">{en ? 'Metric' : 'माप'}</th>
              {cols.map((c) => (
                <th key={c.key} scope="col">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {TEN.map((m) => {
              const now = nowCell(m.key, t, lang);
              return (
                <tr key={m.key}>
                  <th scope="row">
                    {m.n}. {m.title[lang]}
                    <span className="meta-line"> {m.how[lang]}</span>
                  </th>
                  {now != null ? (
                    <td colSpan={3} data-label={en ? 'Now, all villages' : 'अभी, सभी गाँव'}>
                      {now}
                    </td>
                  ) : (
                    cols.map((c) => (
                      <td key={c.key} data-label={c.label}>
                        {groupCell(m.key, t[c.key], lang)}
                        {m.key === 'data' && c.key === 'live' && <span className="meta-line"> {dataNow(t, lang)}</span>}
                      </td>
                    ))
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="pl-asof">
        {en ? 'From the API, GET /public/pilot-metrics, at ' : 'API से, GET /public/pilot-metrics, समय '}
        <span translate="no">{fmtTime(t.as_of, lang)}</span>
      </p>
    </>
  );
}
