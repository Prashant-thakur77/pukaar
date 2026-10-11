import { useMemo, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import {
  ArrowRight,
  ArrowUpRight,
  Ban,
  Bot,
  CircleCheck,
  CircleDashed,
  Clock,
  Lock,
  MessageSquareText,
  PenLine,
  Radar,
  RadioTower,
  Scale,
  ShieldCheck,
  ShieldX,
  Sparkles,
  Truck,
  UserCheck,
  Volume2,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { api } from '../api';
import { CountUp } from '../components/CountUp';
import { LevelBadge } from '../components/Level';
import { PageBand, StatStrip } from '../components/PageBand';
import { Reveal } from '../components/Reveal';
import { ErrorState, Skeleton } from '../components/States';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { fmtAgo } from '../lib/format';
import type { AgentCard, AgentRegistry, AgentState, AgentTrace, TraceKind, TraceRound } from '../types';
import { ValleyLine } from '../components/Art';

type Txt = { hi: string; en: string };
const GITHUB = 'https://github.com/Prashant-thakur77/pukaar';

/** EcoLafaek-style example questions per tool (the tool list itself comes from the API). */
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

/** Starter prompts for Ask Pukaar: each one is routed even without a model (keyword router). */
const STARTERS: Txt[] = [
  TOOL_EXAMPLES.rank_villages,
  { en: 'Which alerts were never acknowledged?', hi: 'किन चेतावनियों का “मिल गया” नहीं आया?' },
  TOOL_EXAMPLES.query_readings,
  { en: 'How many reports in the last 24 hours?', hi: 'पिछले 24 घंटे में कितनी रिपोर्ट?' },
  { en: 'Compare Pandoh with past floods', hi: 'पंडोह की पिछली बाढ़ से तुलना' },
  TOOL_EXAMPLES.query_alerts,
];

const AGENT_ICON: Record<string, LucideIcon> = {
  'drafting-agent': PenLine,
  'analyst-agent': MessageSquareText,
  'report-agent': Sparkles,
  'report-guardrail': ShieldCheck,
  'watch-agent': RadioTower,
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

function StatusPill({ state, label }: { state: AgentState; label: string }) {
  const Icon = state === 'live' || state === 'deterministic' ? CircleCheck : state === 'pending' ? Clock : CircleDashed;
  return (
    <span className={`ag-status is-${state}`}>
      <Icon aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}

function Ext({ href, children, className = '' }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className={className}>
      {children}
      <ArrowUpRight aria-hidden="true" className="how-ext" />
    </a>
  );
}

function AgentCardView({ a, i }: { a: AgentCard; i: number }) {
  const { lang } = useT();
  const en = lang === 'en';
  const Icon = AGENT_ICON[a.id] ?? Bot;
  const warn = (a.findings ?? []).filter((f) => f.severity === 'warn').length;
  return (
    <Reveal as="li" className={`ag-card ag-${a.id}`} delay={(i % 2) * 90}>
      <div className="ag-card-top">
        <span className="ag-tile" translate="no">
          {a.kicker}
        </span>
        <StatusPill state={a.status.state} label={en ? a.status.label_en : a.status.label_hi} />
      </div>
      <div className="ag-head">
        <span className="ag-icon" aria-hidden="true">
          <Icon />
        </span>
        <div>
          <h3 className="ag-name">{en ? a.name_en : a.name_hi}</h3>
          <p className="ag-name-alt" lang={en ? 'hi' : 'en'}>
            {en ? a.name_hi : a.name_en}
          </p>
        </div>
      </div>
      <p className="ag-role">{en ? a.role_en : a.role_hi}</p>
      {a.status.evidence && (
        <p className="ag-evidence" lang={en || !a.status.evidence_hi ? 'en' : 'hi'}>
          {en ? a.status.evidence : a.status.evidence_hi || a.status.evidence}
        </p>
      )}

      <ul className="ag-prims" aria-label={en ? 'AWS primitives' : 'AWS के हिस्से'}>
        {a.primitives.map((p) => (
          <li key={p} translate="no">
            {p}
          </li>
        ))}
      </ul>

      {a.tools.length > 0 && (
        <div className="ag-sec">
          <p className="ag-k">
            <Wrench aria-hidden="true" /> {a.id === 'watch-agent' ? (en ? 'Checks it runs' : 'जो जाँच करता है') : en ? 'Tools it may call' : 'जो टूल चला सकता है'}
          </p>
          <ul className="ag-tools">
            {a.tools.map((t) => (
              <li key={t.name} title={en ? t.description : t.description_hi ?? t.description}>
                <Lock aria-hidden="true" />
                <code>{t.name}</code>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="ag-sec">
        <p className="ag-k ag-k-never">
          <Ban aria-hidden="true" /> {en ? 'May never' : 'कभी नहीं कर सकता'}
        </p>
        <ul className="ag-never">
          {a.never.map((n) => (
            <li key={n.action} title={n.source}>
              <ShieldX aria-hidden="true" />
              <span>{en ? n.en : n.hi}</span>
              {n.source.startsWith('cedar') && <span className="ag-cedar">Cedar</span>}
            </li>
          ))}
        </ul>
      </div>

      <div className="ag-foot">
        <p>
          <span className="ag-k">{en ? 'If it fails' : 'अगर न चले'}</span>
          {en ? a.fallback_en : a.fallback_hi}
        </p>
        <ul className="ag-meta">
          {a.max_turns > 0 && <li>{en ? `max ${a.max_turns} turns` : `अधिकतम ${a.max_turns} चक्कर`}</li>}
          {a.budget_seconds != null && <li>{en ? `${a.budget_seconds} s budget` : `${a.budget_seconds} सेकंड की सीमा`}</li>}
          {a.output_fields.length > 0 && <li translate="no">{`{ ${a.output_fields.join(', ')} }`}</li>}
          {a.access_en && <li>{en ? a.access_en : a.access_hi}</li>}
        </ul>
        {a.id === 'watch-agent' && (
          <Link to="/sensors" className="ag-link">
            {en ? `${warn} open finding${warn === 1 ? '' : 's'} · see the gauges` : `${warn} खुली चेतावनी · गेज देखें`} <ArrowRight aria-hidden="true" />
          </Link>
        )}
      </div>
    </Reveal>
  );
}

function TraceView({ trace }: { trace: AgentTrace }) {
  const { lang } = useT();
  const en = lang === 'en';
  return (
    <ol className="ag-tl">
      {trace.rounds.map((r, i) => {
        const Icon = ROUND_ICON[r.kind] ?? CircleDashed;
        return (
          <Reveal as="li" key={r.n} className={`ag-round is-${r.state} by-${r.actor}`} delay={i * 70}>
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
          </Reveal>
        );
      })}
    </ol>
  );
}

function Traces() {
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
            <LevelBadge level={t.level} size="sm" both={false} lang={lang} />
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

export default function Agents() {
  const { lang } = useT();
  const en = lang === 'en';
  const p = (x: Txt) => x[lang];
  const { data, error, loading, refresh } = usePoll(() => api.agents(), [], 30000);
  const groups = useMemo(() => stackGroups(data), [data]);
  const c = data?.counters;

  // Every read-only tool any agent can call, with the agents that use it.
  const toolRows = useMemo(() => {
    const rows = new Map<string, { name: string; description: string; aws: string; by: string[] }>();
    for (const a of data?.agents ?? []) {
      if (a.id === 'watch-agent') continue;
      for (const t of a.tools) {
        const row = rows.get(t.name) ?? { name: t.name, description: t.description, aws: t.aws, by: [] };
        row.by.push(en ? a.name_en : a.name_hi);
        rows.set(t.name, row);
      }
    }
    return [...rows.values()];
  }, [data, en]);

  return (
    <div className="how agents-page">
      <PageBand
        eyebrow={en ? 'Agents · what they do, what they may never do' : 'एजेंट · क्या करते हैं, क्या कभी नहीं कर सकते'}
        title={en ? 'Agents advise. Code decides.' : 'एजेंट सलाह देते हैं। कोड तय करता है।'}
        lead={
          en
            ? 'Five agents work inside Pukaar. Every tool they call is read-only and checked by a Cedar policy first. None of them can set a level, choose who hears an alert, approve or send.'
            : 'पुकार में पाँच एजेंट काम करते हैं। उनका हर टूल सिर्फ़ पढ़ता है और पहले Cedar नीति से जाँचा जाता है। कोई एजेंट स्तर तय नहीं कर सकता, चेतावनी किसे मिले यह नहीं चुन सकता, न मंज़ूरी दे सकता, न भेज सकता।'
        }
        aside={
          data ? (
            <div className="ag-band-status">
              <StatusPill state={data.model.status.state} label={`${data.model.label} · ${en ? data.model.status.label_en : data.model.status.label_hi}`} />
              <StatusPill state={data.guardrail.status.state} label={`Guardrails · ${en ? data.guardrail.status.label_en : data.guardrail.status.label_hi}`} />
            </div>
          ) : null
        }
        live
      >
        <StatStrip
          stats={[
            { key: 'agents', value: <CountUp value={c ? c.agents : null} lang={lang} />, label: en ? 'Agents' : 'एजेंट' },
            { key: 'tools', value: <CountUp value={c ? c.read_only_tools : null} lang={lang} />, label: en ? 'Read-only tools' : 'सिर्फ़-पढ़ने वाले टूल' },
            { key: 'cedar', value: <CountUp value={c ? c.cedar_policies : null} lang={lang} />, label: en ? 'Cedar policies' : 'Cedar नीतियाँ' },
            {
              key: 'calls',
              value: <CountUp value={c ? c.tool_calls_today : null} lang={lang} />,
              label: en ? `Tool calls today · ${c?.tool_calls_denied_today ?? 0} denied` : `आज टूल कॉल · ${c?.tool_calls_denied_today ?? 0} रोके`,
            },
          ]}
        />
      </PageBand>

      <section className="how-band how-loop ag-cards-band" aria-labelledby="ag-cards-h">
        <div className="wrap-wide">
          <p className="how-eyebrow">{en ? 'The agents' : 'एजेंट'}</p>
          <h2 id="ag-cards-h" className="how-h">
            {en ? 'Who does what' : 'कौन क्या करता है'}
          </h2>
          {loading && !data ? (
            <Skeleton lines={8} />
          ) : error && !data ? (
            <ErrorState error={error} onRetry={() => void refresh()} />
          ) : (
            <ul className="ag-cards">
              {(data?.agents ?? []).map((a, i) => (
                <AgentCardView key={a.id} a={a} i={i} />
              ))}
            </ul>
          )}
          <p className="ag-honest">
            {en
              ? 'Status is read from what the last real draft and report used, never assumed. While Bedrock model access is pending, alerts use the fixed Hindi template and say so.'
              : 'स्थिति आख़िरी असली ड्राफ़्ट और सूचना से पढ़ी जाती है, मानी नहीं जाती। Bedrock मॉडल की अनुमति बाकी रहने तक चेतावनी तय हिंदी ढाँचे से जाती है, और यह साफ़ लिखा रहता है।'}
          </p>
        </div>
      </section>

      <section className="how-band ag-think" aria-labelledby="ag-think-h">
        <div className="wrap-wide ag-think-grid">
          <div className="ag-think-copy">
            <p className="how-eyebrow">{en ? 'A real decision trace' : 'असली फ़ैसले का रिकॉर्ड'}</p>
            <h2 id="ag-think-h" className="how-h">
              {en ? 'How an agent thinks' : 'एजेंट कैसे सोचता है'}
            </h2>
            <p className="how-lead">
              {en
                ? 'Each recent alert, replayed round by round from its stored decision trace: what code read, which rules fired, which tools the agent called and whether Cedar allowed them, who approved, and who heard it.'
                : 'हर हाल की चेतावनी, उसके रिकॉर्ड से चरण दर चरण: कोड ने क्या पढ़ा, कौन-से नियम लगे, एजेंट ने कौन-से टूल चलाए और Cedar ने अनुमति दी या नहीं, किसने मंज़ूरी दी, और किसने सुना।'}
            </p>
            <p className="ag-honest">
              {en
                ? 'No names, usernames, phone numbers or report text are shown. Without model access a trace shows the fixed template, never invented model output.'
                : 'कोई नाम, यूज़रनेम, फ़ोन नंबर या सूचना का पाठ नहीं दिखता। मॉडल की अनुमति के बिना रिकॉर्ड में तय ढाँचा दिखता है, कभी गढ़ा हुआ जवाब नहीं।'}
            </p>
          </div>
          <Traces />
        </div>
      </section>

      <section className="how-band how-cream" aria-labelledby="ag-tools-h">
        <div className="wrap-wide">
          <p className="how-eyebrow">{en ? 'Read-only, Cedar-checked' : 'सिर्फ़ पढ़ना, Cedar से जाँचा'}</p>
          <h2 id="ag-tools-h" className="how-h">
            {en ? 'The tools' : 'टूल'}
          </h2>
          {toolRows.length === 0 ? (
            <Skeleton lines={5} />
          ) : (
            <div className="ag-table-wrap">
              <table className="ag-table">
                <thead>
                  <tr>
                    <th scope="col">{en ? 'Tool' : 'टूल'}</th>
                    <th scope="col">{en ? 'Used by' : 'कौन चलाता है'}</th>
                    <th scope="col">{en ? 'AWS service' : 'AWS सेवा'}</th>
                    <th scope="col">{en ? 'Example question' : 'उदाहरण सवाल'}</th>
                  </tr>
                </thead>
                <tbody>
                  {toolRows.map((r) => (
                    <tr key={r.name}>
                      <th scope="row">
                        <code>{r.name}</code>
                        <span className="ag-td-desc">{r.description}</span>
                      </th>
                      <td data-k={en ? 'Used by' : 'कौन चलाता है'}>{r.by.join(' · ')}</td>
                      <td data-k={en ? 'AWS service' : 'AWS सेवा'} translate="no">
                        {r.aws} · Lambda
                      </td>
                      <td data-k={en ? 'Example question' : 'उदाहरण सवाल'} className="ag-td-q">
                        {TOOL_EXAMPLES[r.name] ? `“${p(TOOL_EXAMPLES[r.name])}”` : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </section>

      <section className="how-band ag-ask" aria-labelledby="ag-ask-h">
        <div className="wrap-wide ag-ask-grid">
          <div>
            <p className="how-eyebrow">{en ? 'For district officers' : 'ज़िला अधिकारियों के लिए'}</p>
            <h2 id="ag-ask-h" className="how-h">
              {en ? 'Ask ' : 'पुकार से '}
              <em className="hl-gold">{en ? 'Pukaar' : 'पूछें'}</em>
            </h2>
            <p className="how-lead">
              {en
                ? 'Officers ask in Hindi or English. The analyst calls the read-only tools, every number is checked against the tool results, and code draws the chart and the map.'
                : 'अधिकारी हिंदी या अंग्रेज़ी में पूछते हैं। विश्लेषक सिर्फ़-पढ़ने वाले टूल चलाता है, हर संख्या टूल के नतीजे से मिलाई जाती है, और चार्ट व नक्शा कोड बनाता है।'}
            </p>
            <ol className="ag-ask-flow">
              <li>{en ? 'Question' : 'सवाल'}</li>
              <li translate="no">Nova · Strands</li>
              <li>{en ? 'Cedar-checked tools' : 'Cedar से जाँचे टूल'}</li>
              <li>{en ? 'Number check' : 'संख्या की जाँच'}</li>
              <li>{en ? 'Chart + map' : 'चार्ट + नक्शा'}</li>
            </ol>
          </div>
          <div className="ag-ask-box">
            <p className="ag-k">
              <Sparkles aria-hidden="true" /> {en ? 'Try a starter question' : 'ये सवाल आज़माएँ'}
            </p>
            <ul className="ag-starters">
              {STARTERS.map((s) => (
                <li key={s.en}>
                  <Link to={`/console?ask=${encodeURIComponent(p(s))}#ask`} className="ag-starter">
                    <span>{p(s)}</span>
                    <ArrowRight aria-hidden="true" />
                  </Link>
                </li>
              ))}
            </ul>
            <p className="ag-ask-note">
              {en
                ? 'Ask Pukaar is for signed-in officers (Cedar action ask_analyst). Without a model, a keyword router answers the same questions with the same tools and says so.'
                : 'पुकार से पूछें सिर्फ़ साइन-इन अधिकारियों के लिए है (Cedar: ask_analyst)। मॉडल न हो तो शब्द-आधारित राउटर इन्हीं टूल से जवाब देता है और यह साफ़ बताता है।'}
            </p>
            <Ext href={`${GITHUB}/blob/main/DEMO.md`} className="how-cite">
              {en ? 'Demo sign-in' : 'डेमो साइन-इन'}
            </Ext>
          </div>
        </div>
      </section>

      <section className="how-band how-loop" aria-labelledby="ag-stack-h">
        <div className="wrap-wide">
          <p className="how-eyebrow">{en ? 'Built on AWS' : 'AWS पर बना'}</p>
          <h2 id="ag-stack-h" className="how-h">
            {en ? 'The stack' : 'पूरी बनावट'}
          </h2>
          <div className="ag-stack">
            {groups.map((g, gi) => (
              <Reveal key={g.key} className="ag-stack-col" delay={gi * 80}>
                <p className="ag-stack-h">
                  <g.icon aria-hidden="true" /> {p(g.title)}
                </p>
                <ul>
                  {g.items.map((s) => (
                    <li key={s.name} className="ag-svc">
                      <span className="ag-svc-name" translate="no">
                        {s.name}
                      </span>
                      <span className="ag-svc-role">{p(s.role)}</span>
                      {s.tag && <span className={`ag-svc-tag is-${s.tag}`}>{p(TAG_TXT[s.tag])}</span>}
                    </li>
                  ))}
                </ul>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      <section className="how-band how-cta" aria-labelledby="ag-cta-h">
        <div className="wrap-wide">
          <h2 id="ag-cta-h" className="how-h">
            {en ? 'From the river ' : 'नदी से '}
            <em className="hl-gold">{en ? 'to the rules' : 'नियमों तक'}</em>
          </h2>
          <div className="how-cta-row">
            <Link to="/sensors" className="btn btn-accent">
              {en ? 'See the sensors' : 'सेंसर देखें'} <ArrowRight aria-hidden="true" />
            </Link>
            <Link to="/how" className="btn how-btn-light">
              {en ? 'The whole loop' : 'पूरा चक्र'}
            </Link>
            <Ext href={GITHUB} className="btn how-btn-light">
              {en ? 'Code on GitHub' : 'GitHub पर कोड'}
            </Ext>
          </div>
        </div>
        <ValleyLine className="cta-valley" />
      </section>
    </div>
  );
}
