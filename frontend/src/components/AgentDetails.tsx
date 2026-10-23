import { useMemo, useState } from 'react';
import {
  Bot,
  CircleDashed,
  PenLine,
  Radar,
  RadioTower,
  Scale,
  ShieldCheck,
  Truck,
  UserCheck,
  Volume2,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { api } from '../api';
import { LevelBadge } from './Level';
import { ErrorState, Skeleton } from './States';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { fmtAgo } from '../lib/format';
import type { AgentRegistry, AgentTrace, TraceKind, TraceRound } from '../types';

/*
 * /how#agents, for engineers: a real alert's decision trace round by round, the read-only tools and the AWS stack.
 * Moved here from the old /agents page; the chapter itself (How.tsx) says the same in plain words first.
 */

type Txt = { hi: string; en: string };

/** Example questions per tool (the tool list itself comes from the API). */
const TOOL_EXAMPLES: Record<string, Txt> = {
  get_village_risk: { en: 'What is Gohar’s level right now, and why?', hi: 'गोहर का स्तर अभी क्या है, और क्यों?' },
  get_recent_reports: { en: 'Any villager reports from Thunag in the last 6 hours?', hi: 'पिछले 6 घंटे में थुनाग से कोई सूचना?' },
  get_past_events: { en: 'When did Pandoh last flood?', hi: 'पंडोह में पिछली बाढ़ कब आई?' },
  get_safe_places: { en: 'Where is the nearest safe place for Janjehli?', hi: 'जंजैहली के लिए सबसे पास सुरक्षित जगह कहाँ है?' },
  rank_villages: { en: 'Which village needs attention first?', hi: 'किस गाँव पर पहले ध्यान दें?' },
  query_readings: { en: 'Show rain and river for Gohar', hi: 'गोहर में बारिश और नदी दिखाओ' },
  query_alerts: { en: 'How many alerts are on record?', hi: 'कितने alert दर्ज हैं?' },
  query_deliveries: { en: 'Which phones never said “मिल गया”?', hi: 'किन फ़ोन से “मिल गया” नहीं आया?' },
  query_reports: { en: 'How many reports in the last 24 hours, by village?', hi: 'पिछले 24 घंटे में गाँववार कितनी रिपोर्ट?' },
  village_stats: { en: 'Compare Pandoh with its past floods', hi: 'पंडोह की पिछली बाढ़ों से तुलना करो' },
};

const ROUND_ICON: Record<TraceKind, LucideIcon> = {
  sense: Radar,
  rules: Scale,
  tools: Wrench,
  draft: PenLine,
  approve: UserCheck,
  deliver: Volume2,
};

const ACTOR: Record<TraceRound['actor'], Txt> = {
  code: { en: 'Code', hi: 'कोड' },
  agent: { en: 'Agent', hi: 'एजेंट' },
  template: { en: 'Template', hi: 'तय ढाँचा' },
  person: { en: 'Person', hi: 'इंसान' },
  system: { en: 'System', hi: 'सिस्टम' },
};

const ROUND_STATE: Record<TraceRound['state'], Txt> = {
  ok: { en: 'Done', hi: 'हुआ' },
  fallback: { en: 'Fallback', hi: 'विकल्प' },
  pending: { en: 'Waiting', hi: 'इंतज़ार' },
  skipped: { en: 'Skipped', hi: 'छोड़ा' },
  deny: { en: 'Denied', hi: 'रोका' },
};

type Svc = { name: string; role: Txt; tag?: 'live' | 'pending' | 'deploy' | 'building' | 'fallback' };
type Group = { key: string; title: Txt; icon: LucideIcon; items: Svc[] };

function stackGroups(reg: AgentRegistry | null): Group[] {
  const model = reg?.model.status.state;
  const modelTag: Svc['tag'] = model === 'live' ? 'live' : model === 'pending' ? 'pending' : model ? 'fallback' : undefined;
  const gr = reg?.guardrail.status.state;
  const grTag: Svc['tag'] = gr === 'live' ? 'live' : gr === 'pending' ? 'deploy' : gr ? 'fallback' : undefined;
  return [
    {
      key: 'agents',
      title: { en: 'Agents', hi: 'एजेंट' },
      icon: Bot,
      items: [
        { name: `Amazon Bedrock${reg ? ` (${reg.model.label})` : ''}`, role: { en: 'Drafts, answers and reads reports', hi: 'ड्राफ़्ट, जवाब और सूचना समझना' }, tag: modelTag },
        { name: 'Strands Agents', role: { en: 'Agent loop, typed output, tool hooks', hi: 'एजेंट लूप, तय ढाँचे में जवाब, टूल हुक' } },
        { name: 'Amazon Transcribe', role: { en: 'Hindi voice reports to text (hi-IN)', hi: 'हिंदी आवाज़ की सूचना को लिखित में' } },
      ],
    },
    {
      key: 'sensors',
      title: { en: 'Sensors', hi: 'सेंसर' },
      icon: RadioTower,
      items: [
        { name: 'AWS IoT Core', role: { en: 'MQTT over TLS, one X.509 certificate per gauge', hi: 'MQTT, हर गेज का अपना X.509 प्रमाणपत्र' }, tag: 'building' },
        { name: 'AWS Lambda', role: { en: 'Ingest, rules, sweep and the Watch agent', hi: 'रीडिंग लेना, नियम, जाँच और निगरानी एजेंट' } },
        { name: 'Amazon DynamoDB', role: { en: 'Readings, alerts, append-only audit', hi: 'रीडिंग, चेतावनियाँ, न मिटने वाला ऑडिट' } },
        { name: 'Amazon EventBridge', role: { en: 'Forecast sweep every 15 minutes', hi: 'हर 15 मिनट पूर्वानुमान की जाँच' } },
      ],
    },
    {
      key: 'delivery',
      title: { en: 'Delivery', hi: 'पहुँचाना' },
      icon: Truck,
      items: [
        { name: 'AWS Step Functions', role: { en: 'Waits for one officer’s tap, then the next', hi: 'एक अधिकारी की मंज़ूरी का इंतज़ार, फिर अगला' } },
        { name: 'Amazon Polly', role: { en: 'The alert spoken in Hindi (Kajal)', hi: 'चेतावनी हिंदी में बोली जाती है (काजल)' } },
        { name: 'Amazon API Gateway', role: { en: 'Public, officer and gauge routes', hi: 'आम लोगों, अधिकारी और गेज के रास्ते' } },
        { name: 'Amazon S3', role: { en: 'Alert audio, photos and voice notes', hi: 'चेतावनी की आवाज़, फ़ोटो, वॉइस नोट' } },
        { name: 'AWS Amplify', role: { en: 'This web app, offline-ready', hi: 'यह वेब ऐप, बिना नेट भी' } },
      ],
    },
    {
      key: 'safety',
      title: { en: 'Safety', hi: 'सुरक्षा' },
      icon: ShieldCheck,
      items: [
        { name: 'Amazon Bedrock Guardrails', role: { en: 'Screens villager text before agents', hi: 'एजेंट से पहले गाँव वालों का लिखा जाँचता है' }, tag: grTag },
        { name: 'Cedar', role: { en: 'Who may do what; agents read-only', hi: 'कौन क्या कर सकता है; एजेंट सिर्फ़ पढ़ें' } },
        { name: 'Amazon Cognito', role: { en: 'Officer and pradhan sign-in', hi: 'अधिकारी और प्रधान का साइन-इन' } },
        { name: 'Amazon CloudWatch', role: { en: 'Logs, model latency, failover metrics', hi: 'लॉग, मॉडल की देरी, फ़ेलओवर' } },
      ],
    },
  ];
}

const TAG_TXT: Record<NonNullable<Svc['tag']>, Txt> = {
  live: { en: 'Live', hi: 'चालू' },
  pending: { en: 'Pending access', hi: 'अनुमति बाकी' },
  deploy: { en: 'Pending deploy', hi: 'तैनाती बाकी' },
  building: { en: 'Being wired', hi: 'जुड़ रहा है' },
  fallback: { en: 'Fallback', hi: 'विकल्प' },
};

function TraceView({ trace }: { trace: AgentTrace }) {
  const { lang } = useT();
  const en = lang === 'en';
  return (
    <ol className="ag-tl">
      {trace.rounds.map((r) => {
        const Icon = ROUND_ICON[r.kind] ?? CircleDashed;
        return (
          <li key={r.n} className={`ag-round is-${r.state} by-${r.actor}`}>
            <span className="ag-node" aria-hidden="true">
              <Icon />
            </span>
            <div className="ag-round-body">
              <div className="ag-round-top">
                <span className="ag-round-n">{en ? `Round ${String(r.n).padStart(2, '0')}` : `चरण ${r.n}`}</span>
                <span className={`ag-actor by-${r.actor}`}>{ACTOR[r.actor][lang]}</span>
                <span className={`ag-rstate is-${r.state}`}>{ROUND_STATE[r.state][lang]}</span>
              </div>
              <h3 className="ag-round-title">{en ? r.title_en : r.title_hi}</h3>
              <span className="how-aws ag-round-aws" translate="no">
                {r.aws}
              </span>
              <dl className="ag-facts">
                {r.facts.map((f, j) => (
                  <div key={`${f.en}-${j}`}>
                    <dt>{en ? f.en : f.hi}</dt>
                    <dd translate="no">{String(f.v)}</dd>
                  </div>
                ))}
              </dl>
              {(r.note_en || r.note_hi) && <p className="ag-note">{en ? r.note_en : r.note_hi}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

export function Traces() {
  const { lang } = useT();
  const en = lang === 'en';
  const { data, error, loading, refresh } = usePoll(() => api.agentTraces(8), [], 60000);
  const [pick, setPick] = useState<string | null>(null);
  const traces = data ?? [];
  // Open on a live (not replayed) alert that ran to the end, when there is one.
  const done = (t: AgentTrace) => t.rounds.at(-1)?.state === 'ok';
  const best = traces.find((t) => !t.replay && done(t)) ?? traces.find((t) => !t.replay) ?? traces.find(done) ?? traces[0] ?? null;
  const current = traces.find((t) => t.alert_id === pick) ?? best;

  if (loading && !data) return <Skeleton lines={6} />;
  if (error && !data) return <ErrorState error={error} onRetry={() => void refresh()} compact />;
  if (!current)
    return (
      <div className="ag-empty">
        <p className="ag-empty-word" aria-hidden="true">
          {en ? 'Quiet' : 'शांत'}
        </p>
        <p>
          {en
            ? 'No alert has been raised yet, so there is no trace to show. The first real alert appears here, round by round.'
            : 'अभी तक कोई चेतावनी नहीं उठी, इसलिए दिखाने को कोई रिकॉर्ड नहीं। पहली असली चेतावनी यहाँ चरण दर चरण दिखेगी।'}
        </p>
      </div>
    );
  return (
    <div className="ag-trace">
      <div className="ag-trace-pick" role="tablist" aria-label={en ? 'Recent alerts' : 'हाल की चेतावनियाँ'}>
        {traces.map((t) => (
          <button
            key={t.alert_id}
            type="button"
            role="tab"
            aria-selected={t.alert_id === current.alert_id}
            className={`ag-pick${t.alert_id === current.alert_id ? ' is-on' : ''}`}
            onClick={() => setPick(t.alert_id)}
          >
            <LevelBadge level={t.level} size="sm" both={false} lang={lang} plain={t.level !== 'critical'} />
            <span className="ag-pick-name">{en ? t.village_name : t.village_name_hi}</span>
            <span className="ag-pick-time">{fmtAgo(t.created_at, lang)}</span>
            {t.replay && <span className="ag-flag">{en ? 'Replay' : 'रीप्ले'}</span>}
            {t.drill && <span className="ag-flag">{en ? 'Drill' : 'अभ्यास'}</span>}
          </button>
        ))}
      </div>
      {current.replay && (
        <p className="ag-replay-note">
          {en
            ? 'Replay: archived real data run through the same code. Replay alerts never reach real phones.'
            : 'रीप्ले: पुराना असली डेटा, उसी कोड से। रीप्ले की चेतावनी असली फ़ोन तक कभी नहीं जाती।'}
        </p>
      )}
      <TraceView trace={current} />
    </div>
  );
}


/** Every read-only tool an agent may call, with who calls it and an example question. */
export function ToolTable({ reg }: { reg: AgentRegistry | null }) {
  const { lang } = useT();
  const en = lang === 'en';
  const rows = useMemo(() => {
    const m = new Map<string, { name: string; aws: string; by: string[] }>();
    for (const a of reg?.agents ?? []) {
      if (a.id === 'watch-agent') continue;
      for (const t of a.tools) {
        const row = m.get(t.name) ?? { name: t.name, aws: t.aws, by: [] };
        row.by.push(en ? a.name_en : a.name_hi);
        m.set(t.name, row);
      }
    }
    return [...m.values()];
  }, [reg, en]);
  if (!rows.length) return null;
  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={en ? 'Read-only tools' : 'सिर्फ़ पढ़ने वाले टूल'}>
      <table className="data-table stack-sm xp-tools">
        <thead>
          <tr>
            <th scope="col">{en ? 'Tool' : 'टूल'}</th>
            <th scope="col">{en ? 'Used by' : 'कौन चलाता है'}</th>
            <th scope="col">{en ? 'Example question' : 'उदाहरण सवाल'}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.name}>
              <th scope="row">
                <code>{r.name}</code>
                <span className="xp-td-sub" translate="no">
                  {r.aws} · Lambda
                </span>
              </th>
              <td data-label={en ? 'Used by' : 'कौन चलाता है'}>{r.by.join(' · ')}</td>
              <td data-label={en ? 'Example question' : 'उदाहरण सवाल'}>{TOOL_EXAMPLES[r.name] ? `“${TOOL_EXAMPLES[r.name][lang]}”` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The AWS services behind the agents, the sensors, delivery and safety, with what each is for. */
export function Stack({ reg }: { reg: AgentRegistry | null }) {
  const { lang } = useT();
  const groups = useMemo(() => stackGroups(reg), [reg]);
  return (
    <div className="xp-stack">
      {groups.map((g) => (
        <div key={g.key}>
          <p className="xp-stack-h">
            <g.icon aria-hidden="true" /> {g.title[lang]}
          </p>
          <ul>
            {g.items.map((s) => (
              <li key={s.name}>
                <span className="xp-stack-name" translate="no">
                  {s.name}
                </span>{' '}
                <span className="xp-stack-role">{s.role[lang]}</span>
                {s.tag && <span className={`ag-svc-tag is-${s.tag}`}>{TAG_TXT[s.tag][lang]}</span>}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
