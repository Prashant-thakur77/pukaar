import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Layers } from 'lucide-react';
import { ApiError } from '../../api';
import { HoldToConfirm } from '../../components/HoldToConfirm';
import { LevelIcon } from '../../components/Level';
import { ReplayChip } from '../../components/Chips';
import { DeniedNote, ErrorState, Skeleton } from '../../components/States';
import { usePoll } from '../../hooks/usePoll';
import { dict, useT } from '../../i18n';
import { istClock } from '../../lib/answerText';
import { shortReason } from '../../lib/evidence';
import { findGroup, groupDecisions, groupPath, reachApi, type AlertGroup, type GroupResult } from '../../lib/reach';
import { useConsole } from './consoleContext';
import '../../styles/reach.css';

/*
 * Grouped approval (backend services/group_approval.py): the villages of one district that wait together from one
 * cause. The evidence they share comes first, then each village's level and exact message, each one approved
 * unless the officer marks it declined; then one hold-to-approve. Underneath, every village is still its own
 * decision: its own Cedar check (district scope), its own audit row and its own workflow task token.
 */

export default function GroupReview() {
  const { lang } = useT();
  const hi = lang === 'hi';
  const c = useConsole();
  const [params] = useSearchParams();
  const d = params.get('d');
  const groups = usePoll(() => reachApi.groups(d ?? undefined), [d], 15_000);
  const group = findGroup(groups.data ?? [], d, params.get('c'), params.get('s'));
  const [results, setResults] = useState<GroupResult[] | null>(null);

  const back = (
    <Link to="/console/inbox" className="go-link">
      <ArrowLeft aria-hidden="true" /> {hi ? 'इनबॉक्स' : 'Inbox'}
    </Link>
  );
  if (results) {
    return (
      <div className="grp">
        {back}
        <Done results={results} />
      </div>
    );
  }
  return (
    <div className="grp">
      {back}
      <h1 className="ib-h">
        <Layers aria-hidden="true" /> {hi ? 'समूह में समीक्षा' : 'Review as a group'}
      </h1>
      {groups.loading && !groups.data ? (
        <Skeleton lines={4} />
      ) : groups.error && !groups.data ? (
        <ErrorState error={groups.error} onRetry={groups.refresh} compact />
      ) : !group ? (
        <p>{hi ? 'यह समूह अब नहीं है: इसके गाँव तय हो चुके या अलग हो गए।' : 'This group is gone: its villages were decided or no longer wait together.'}</p>
      ) : (
        <Review group={group} canDecide={c.officer} onDone={(r) => {
          setResults(r);
          c.refreshAlerts();
        }} />
      )}
    </div>
  );
}

function Review({ group: g, canDecide, onDone }: { group: AlertGroup; canDecide: boolean; onDone: (r: GroupResult[]) => void }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const [declined, setDeclined] = useState<Set<string>>(new Set());
  const [reason, setReason] = useState('');
  const [err, setErr] = useState<ApiError | null>(null);
  const nApprove = g.villages.length - declined.size;
  const nDecline = declined.size;
  const decisions = useMemo(() => groupDecisions(g.villages, declined), [g.villages, declined]);
  const toggle = (id: string, decline: boolean) =>
    setDeclined((s) => {
      const next = new Set(s);
      if (decline) next.add(id);
      else next.delete(id);
      return next;
    });
  const submit = async () => {
    setErr(null);
    try {
      const r = await reachApi.decideGroup({ decisions, reason: reason.trim() || undefined, group_id: g.id });
      onDone(r.results);
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
      throw e;
    }
  };
  const label = hi
    ? `${nApprove} मंज़ूर करें${nDecline ? `, ${nDecline} अस्वीकार` : ''}`
    : `approve ${nApprove}${nDecline ? `, decline ${nDecline}` : ''}`;
  return (
    <>
      <p className="dp-sub">
        <span>
          {hi ? `${g.district}: ${g.count} गाँव एक साथ, कारण ${g.cause_hi}` : `${g.district}: ${g.count} villages together, from ${g.cause_en}`}
        </span>
        <span>
          {istClock(g.shared.first_at)}–{istClock(g.shared.last_at)} IST
        </span>
        {g.replay && <ReplayChip />}
      </p>

      <section className="grp-shared" aria-labelledby="grp-shared-h">
        <h2 id="grp-shared-h" className="dp-sec-h">
          {hi ? 'सबके लिए एक जैसे सबूत' : 'Evidence they share'}
        </h2>
        <ul>
          {(hi ? g.shared.drivers_hi : g.shared.drivers_en).map((x) => (
            <li key={x}>{x}</li>
          ))}
          {g.shared.official.map((o) => (
            <li key={o.source}>
              {o.name}: {o.detail ?? o.level ?? ''}
            </li>
          ))}
          {shortReason(g.shared.rules, lang) && <li>{shortReason(g.shared.rules, lang)}</li>}
        </ul>
      </section>

      <h2 className="dp-sec-h">{hi ? 'हर गाँव: स्तर और संदेश' : 'Each village: level and message'}</h2>
      <ul className="grp-villages">
        {g.villages.map((v) => {
          const off = declined.has(v.alert_id);
          const name = hi ? v.village_name_hi : v.village_name;
          return (
            <li key={v.alert_id} className={`grp-village lv-${v.level}${off ? ' is-declined' : ''}`}>
              <p className="grp-village-head">
                <LevelIcon level={v.level} />
                <span lang="hi">{dict[`level.${v.level}`].hi}</span>
                {!hi && <span>{dict[`level.${v.level}`].en}</span>}
                <span aria-hidden="true">·</span>
                <span>{name}</span>
                <span className="dp-aud-sub">{hi ? `${v.recipients_count} लोग` : `${v.recipients_count} people`}</span>
                <Link className="link" to={`/console/inbox/${v.alert_id}`}>
                  {hi ? 'अकेले खोलें' : 'Open alone'}
                </Link>
              </p>
              <blockquote className="dp-msg" lang="hi">
                {v.text_hi}
              </blockquote>
              <details className="dp-en">
                <summary>{hi ? 'अंग्रेज़ी में' : 'In English'}</summary>
                <p lang="en">{v.text_en}</p>
              </details>
              {canDecide && (
                <fieldset className="grp-choice">
                  <legend className="sr-only">{name}</legend>
                  <label>
                    <input type="radio" name={`grp-${v.alert_id}`} checked={!off} onChange={() => toggle(v.alert_id, false)} />
                    {hi ? 'मंज़ूर' : 'Approve'}
                  </label>
                  <label>
                    <input type="radio" name={`grp-${v.alert_id}`} checked={off} onChange={() => toggle(v.alert_id, true)} />
                    {hi ? 'अस्वीकार' : 'Decline'}
                  </label>
                </fieldset>
              )}
            </li>
          );
        })}
      </ul>

      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
      {canDecide ? (
        <div className="dp-actions">
          {nDecline > 0 && (
            <label className="field">
              <span className="field-label">{hi ? 'अस्वीकार का कारण (वैकल्पिक)' : 'Reason for declining (optional)'}</span>
              <input className="input-lg" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} />
            </label>
          )}
          <HoldToConfirm
            className="dp-hold"
            onConfirm={submit}
            text={{
              idle: hi ? `दबाए रखें: ${label}` : `Hold to ${label}`,
              holding: hi ? 'दबाए रखें…' : 'Keep holding…',
              almost: hi ? 'छोड़ें नहीं…' : 'Almost…',
              sending: hi ? 'भेज रहे हैं…' : 'Sending…',
              done: hi ? 'हो गया' : 'Done',
              hint: hi ? '1 सेकंड दबाए रखें' : 'Hold for 1 second',
              confirmQ: hi ? `पक्का? ${label}` : `Sure? ${label}`,
              confirmYes: hi ? 'हाँ' : 'Yes',
              confirmNo: hi ? 'रद्द' : 'Cancel',
            }}
          />
          <p className="dp-meta">
            {hi
              ? 'हर गाँव की अपनी जाँच (ज़िला), अपना ऑडिट और अपनी मंज़ूरी होती है।'
              : 'Each village is still checked on its own (your district), audited on its own and approved with its own token.'}
          </p>
        </div>
      ) : (
        <p className="dp-meta">{hi ? 'केवल ज़िला अधिकारी तय कर सकते हैं।' : 'Only a district officer can decide.'}</p>
      )}
    </>
  );
}

const OUTCOME: Record<GroupResult['outcome'], { en: string; hi: string }> = {
  decided: { en: 'done', hi: 'हो गया' },
  denied: { en: 'not allowed', hi: 'अनुमति नहीं' },
  late: { en: 'too late: no longer waiting', hi: 'देर हो गई: अब प्रतीक्षा में नहीं' },
  retry: { en: 'could not reach the workflow; try this one again', hi: 'वर्कफ़्लो तक नहीं पहुँचे; फिर कोशिश करें' },
  missing: { en: 'not found', hi: 'नहीं मिला' },
};

function Done({ results }: { results: GroupResult[] }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  return (
    <div role="alert">
      <h1 className="ib-h">{hi ? 'समूह का फ़ैसला' : 'The group decision'}</h1>
      <ul className="grp-result">
        {results.map((r) => (
          <li key={r.alert_id} className={r.outcome === 'decided' ? '' : 'is-bad'}>
            {r.village_name ?? r.alert_id}: {r.decision === 'approved' ? (hi ? 'मंज़ूर' : 'approved') : hi ? 'अस्वीकार' : 'declined'} ·{' '}
            {OUTCOME[r.outcome][lang]}
            {r.reason && r.outcome !== 'decided' ? ` (${r.reason})` : ''}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The inbox banner: the biggest group of villages waiting together in the district on screen. */
export function GroupBanner({ district }: { district: string }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const groups = usePoll(() => reachApi.groups(district || undefined), [district], 30_000);
  const g = groups.data?.[0];
  if (!g) return null;
  return (
    <div className="grp-banner" role="status">
      <Layers aria-hidden="true" />
      <p>
        {hi
          ? `${g.district} के ${g.count} गाँव एक साथ प्रतीक्षा में (${g.cause_hi})।`
          : `${g.count} villages of ${g.district} are waiting together (${g.cause_en}).`}
      </p>
      <Link className="btn btn-sm btn-accent" to={groupPath(g)}>
        {hi ? 'समूह में देखें' : 'Review as a group'}
      </Link>
    </div>
  );
}
