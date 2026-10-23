import type { ReactNode } from 'react';
import { api } from '../api';
import { ErrorState, Skeleton } from './States';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { fmtNumber, fmtTime } from '../lib/format';
import type { Lang } from '../store';
import type { PilotFalseAlarms, PilotGroup, PilotMetrics } from '../types';

/*
 * What has been measured so far (moved from /pilot to /proof): drills to real phones, live alerts, and false alarms
 * by rule, counted by the API from stored records. Where nothing is measured it says so in words.
 */

function NotYet() {
  const { lang } = useT();
  return <span className="pl-nm">{lang === 'en' ? 'not measured yet' : 'अभी मापा नहीं'}</span>;
}

function Measure({ value, label, note }: { value: ReactNode; label: string; note?: string }) {
  return (
    <li className="pl-stat">
      <span className="pl-stat-num">{value}</span>
      <span className="pl-stat-label">{label}</span>
      {note && <span className="pl-stat-note">{note}</span>}
    </li>
  );
}

function minutes(m: number | null, lang: Lang): ReactNode {
  if (m == null) return <NotYet />;
  return (
    <>
      {fmtNumber(m, lang, 1)}
      <small> {lang === 'en' ? 'min' : 'मिनट'}</small>
    </>
  );
}

function share(g: PilotGroup, lang: Lang): ReactNode {
  if (g.ack_share == null) return <NotYet />;
  return `${fmtNumber(g.ack_share * 100, lang, 0)}%`;
}

const rate = (r: number | null, lang: Lang) => (r == null ? <NotYet /> : `${fmtNumber(r * 100, lang, 0)}%`);

/** "Was this real?" after each closed live alert, counted per rule (api/pilot.py false_alarms). */
function FalseAlarms({ fa }: { fa: PilotFalseAlarms }) {
  const { lang } = useT();
  const en = lang === 'en';
  return (
    <>
      <h3 className="pl-h3">{en ? 'Was it real? False alarms by rule' : 'क्या यह असली था? हर नियम की झूठी चेतावनियाँ'}</h3>
      <ul className="pl-stats">
        <Measure
          value={fmtNumber(fa.closed_alerts, lang)}
          label={en ? 'Live alerts raised and closed' : 'उठी और बंद हुई असली चेतावनियाँ'}
          note={en ? 'Sent or not: one that expired without approval counts here' : 'भेजी गई हों या नहीं: बिना मंज़ूरी समाप्त हुई भी गिनी जाती है'}
        />
        <Measure value={fmtNumber(fa.real_flood, lang)} label={en ? 'Real flood' : 'असली बाढ़'} />
        <Measure value={fmtNumber(fa.no_flood, lang)} label={en ? 'No flood' : 'बाढ़ नहीं आई'} note={en ? `${fa.unknown} unknown, ${fa.not_set} not answered yet` : `${fa.unknown} पता नहीं, ${fa.not_set} का जवाब बाकी`} />
        <Measure value={rate(fa.false_alarm_rate, lang)} label={en ? 'False-alarm rate' : 'झूठी चेतावनी दर'} note={en ? 'No flood ÷ (real + no flood)' : 'बाढ़ नहीं ÷ (असली + बाढ़ नहीं)'} />
      </ul>
      {fa.by_rule.length > 0 && (
        <ul className="pl-rows">
          {fa.by_rule.map((r) => (
            <li key={r.rule}>
              <span className="pl-row-k" translate="no">
                {r.rule}
              </span>
              <span>
                {rate(r.false_alarm_rate, lang)}{' '}
                <span className="meta-line">
                  {en
                    ? `${r.alerts} alerts · ${r.real_flood} real · ${r.no_flood} no flood · ${r.unknown} unknown · ${r.not_set} not answered`
                    : `${r.alerts} चेतावनियाँ · ${r.real_flood} असली · ${r.no_flood} बाढ़ नहीं · ${r.unknown} पता नहीं · ${r.not_set} बाकी`}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

function MeasuredBody({ m }: { m: PilotMetrics }) {
  const { lang } = useT();
  const en = lang === 'en';
  const d = m.drills;
  const l = m.live;
  return (
    <>
      <h3 className="pl-h3">{en ? 'Drills: labelled tests to real phones' : 'अभ्यास: असली फ़ोन पर, साफ़ लिखा परीक्षण'}</h3>
      <ul className="pl-stats">
        <Measure value={fmtNumber(d.alerts, lang)} label={en ? 'Drill alerts sent' : 'भेजे गए अभ्यास संदेश'} />
        <Measure
          value={fmtNumber(d.reached, lang)}
          label={en ? 'Phones reached' : 'फ़ोन तक पहुँचे'}
          note={
            d.demo_recipients
              ? en
                ? `Of ${fmtNumber(d.delivered ?? d.reached, lang)} delivered (the count on each alert); ${fmtNumber(d.demo_recipients, lang)} demo recipients without a phone not counted`
                : `कुल ${fmtNumber(d.delivered ?? d.reached, lang)} तक पहुँचा (हर चेतावनी पर यही गिनती); बिना फ़ोन वाले ${fmtNumber(d.demo_recipients, lang)} डेमो नाम नहीं गिने`
              : en
                ? 'Summed over drills; demo recipients without a phone not counted'
                : 'सब अभ्यासों का जोड़; बिना फ़ोन वाले डेमो नाम नहीं गिने'
          }
        />
        <Measure value={share(d, lang)} label={en ? 'Pressed “मिल गया”' : '“मिल गया” दबाया'} />
        <Measure
          value={minutes(d.median_minutes_first_ack, lang)}
          label={en ? 'Median, send to first “मिल गया”' : 'मध्य समय, भेजने से पहले “मिल गया” तक'}
        />
      </ul>
      <h3 className="pl-h3">{en ? 'Live flood alerts' : 'असली बाढ़ चेतावनियाँ'}</h3>
      {l.alerts === 0 ? (
        // A zero is a sentence, not a trophy (spec C17).
        <p className="xp-p">
          {en
            ? 'No real flood alert has been sent yet, so nothing about live alerts is measured. Replays and drills are never counted here.'
            : 'अब तक कोई असली बाढ़ चेतावनी नहीं भेजी गई, इसलिए असली चेतावनियों का कुछ मापा नहीं गया। रीप्ले और अभ्यास यहाँ कभी नहीं गिने जाते।'}
        </p>
      ) : (
      <ul className="pl-stats">
        <Measure value={fmtNumber(l.alerts, lang)} label={en ? 'Live alerts sent' : 'भेजी गई असली चेतावनियाँ'} note={en ? 'Never replays, never drills' : 'रीप्ले और अभ्यास नहीं'} />
        <Measure value={fmtNumber(l.reached, lang)} label={en ? 'Phones reached' : 'फ़ोन तक पहुँचे'} />
        <Measure value={share(l, lang)} label={en ? 'Pressed “मिल गया”' : '“मिल गया” दबाया'} />
        <Measure
          value={minutes(l.median_minutes_first_ack, lang)}
          label={en ? 'Median, send to first “मिल गया”' : 'मध्य समय, भेजने से पहले “मिल गया” तक'}
        />
      </ul>
      )}

      {m.false_alarms && m.false_alarms.closed_alerts > 0 && <FalseAlarms fa={m.false_alarms} />}

      <p className="pl-asof">
        {en ? 'From the API, GET /public/pilot-metrics, at ' : 'API से, GET /public/pilot-metrics, समय '}
        <span translate="no">{fmtTime(m.as_of, lang)}</span>
      </p>
    </>
  );
}


export function Measured() {
  const { lang } = useT();
  const { data, error, loading, refresh } = usePoll(() => api.pilotMetrics(), [], 0);
  if (data) return <MeasuredBody m={data} />;
  if (error) return <ErrorState error={error} onRetry={() => void refresh()} />;
  return loading ? <Skeleton lines={6} /> : <p>{lang === 'hi' ? 'अभी कुछ नहीं' : 'Nothing yet'}</p>;
}
