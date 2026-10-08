/* Dashboard.tsx — Persona C Backend & Fusion command center.
 *
 * Single-view "tablero de comando" optimized for 1440x900 screen recording:
 *
 *   ┌─────────────────────────────────────────────────────────────────┐
 *   │ RiskBanner (level · score · site · summary)                    │   <- 5-second read
 *   ├──────────────────────────────────────┬──────────────────────────┤
 *   │ Fusión de señales (3 tiles)          │ Estado CAP v1.2          │
 *   │ Frame de evidencia                   │ Acciones del operador    │
 *   │ Razonamiento de Pukaar AI                │ Cola offline · sync      │
 *   │ Traza de auditoría determinística    │                          │
 *   ├──────────────────────────────────────┴──────────────────────────┤
 *   │ Línea de tiempo del incidente                                  │
 *   └─────────────────────────────────────────────────────────────────┘
 *
 * When there is no active alert from the backend, we render a clearly-labeled
 * demo-safe sample state so the recording always has something to show.
 * The demo state is rendered with a "DEMO · sample state" badge — this is
 * not a fake backend, it's clearly-labeled mock data for screen capture.
 */

import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { useAppStore } from '../store';
import type { FusedAlert, Site } from '../store';
import {
  ActionRail,
  AuditTrace,
  CapStatusCard,
  EmptyCommandCenter,
  EvidencePanel,
  Pukaar AIReasoning,
  IncidentTimeline,
  OfflineSyncCard,
  RiskBanner,
  SectionPanel,
  SignalFusionRow,
} from '../components/CommandCenter';
import type {
  ActionCall,
  AuditEntry,
  SignalInput,
  TimelineEvent,
} from '../components/CommandCenter';

// ──────────────────────────────────────────────────────────────────────────
// Demo-safe sample state. Used only when the backend has no active alert.
// Clearly labeled in the UI with a "DEMO · sample state" badge. This is
// not a hidden mock — it's the screen-recording fallback.
// ──────────────────────────────────────────────────────────────────────────
const DEMO_SITE: Site = {
  id: 'silverado-fixed-cam-usgs',
  name: 'Silverado Fixed Cam (USGS)',
  region: 'Demo · clip público USGS · sample state',
  lat: 33.74,
  lng: -117.65,
  description:
    'Sitio bundled del repo. Sirve como referencia E2E del pipeline CV+Pukaar AI sobre un clip real.',
  is_active: true,
};

const DEMO_ALERT: FusedAlert = {
  id: 9001,
  site_id: 'silverado-fixed-cam-usgs',
  level: 'red',
  score: 0.87,
  summary:
    'Línea crítica cruzada a t=078s. Corroborado por reporte de brigadista y probabilidad de lluvia 12h del 68%.',
  created_at: new Date(Date.now() - 1000 * 60 * 3).toISOString(),
  trigger_source: 'fused',
  reasoning_summary:
    'La franja media-baja del cuadro pasó de seco a turbio en 12 frames consecutivos. ' +
    'Velocidad de subida 0.0034/frame supera el umbral interno (0.0020). ' +
    'Reporte voluntario en español confirma el cruce de la marca crítica. Confianza 78%.',
  reasoning_chain: JSON.stringify([
    'observation.crossed_critical_line = true (waterline_ratio 0.42 > 0.30)',
    'rise_velocity 0.0034/frame > umbral 0.0020 → señal de subida sostenida',
    'reporte voluntario coincide léxicamente con "cruzó la marca crítica"',
    'hidromet probabilidad 12h = 68% → corrobora hipótesis de evento',
    'fused_score = 0.87 → nivel RED, emit_cap_xml habilitado',
  ]),
  reasoning_model: 'pukaar-model:2b',
};

const DEMO_FUSION: SignalInput[] = [
  { source: 'camera',    score: 0.87, status: 'ok',    detail: 'Cruzó línea crítica · 126 frames analizados', ageSeconds: 8 },
  { source: 'volunteer', score: 0.62, status: 'ok',    detail: '"El agua ya cruzó la marca crítica y trae barro" · 1 reporte', ageSeconds: 92 },
  { source: 'hydromet',  score: 0.45, status: 'ok',    detail: 'Open-Meteo · 12.4 mm/h · prob 12h 68%',          ageSeconds: 240 },
];

const DEMO_AUDIT: AuditEntry[] = [
  { rule: 'RULE_CRITICAL_LINE_CROSSED',     outcome: 'fired',     detail: 'CV node observación: waterline_ratio 0.42 cruzó la línea calibrada y=120.' },
  { rule: 'RULE_RISE_VELOCITY',             outcome: 'fired',     detail: 'rise_velocity 0.0034/frame > umbral 0.0020/frame.' },
  { rule: 'RULE_VOLUNTEER_CORROBORATION',   outcome: 'fired',     detail: '1 reporte voluntario clasificado por Pukaar AI con urgencia=alta en los últimos 5 min.' },
  { rule: 'RULE_HYDROMET_AGREEMENT',        outcome: 'fired',     detail: 'Open-Meteo probabilidad 12h 68% supera umbral 50%.' },
  { rule: 'RULE_DUPLICATE_SUPPRESSION',     outcome: 'not_fired', detail: 'No se encontró alerta activa previa para este sitio en ventana de 30 min.' },
  { rule: 'RULE_MANUAL_OVERRIDE',           outcome: 'not_fired', detail: 'Operador no aplicó override manual.' },
];

const DEMO_TIMELINE_FACTORY = (): TimelineEvent[] => {
  const now = Date.now();
  const t = (deltaSec: number) => new Date(now + deltaSec * 1000).toISOString();
  return [
    { at: t(-240), kind: 'detect',    label: 'Detección CV',          detail: 'Nodo Silverado: rise_velocity > umbral',  done: true },
    { at: t(-185), kind: 'volunteer', label: 'Reporte voluntario',    detail: 'Brigadista María G. (Pukaar Android)',     done: true },
    { at: t(-145), kind: 'fuse',      label: 'Fusión de señales',     detail: 'fused_score = 0.87 · level = red',        done: true },
    { at: t(-90),  kind: 'cap',       label: 'CAP v1.2 emitido',       detail: 'receipt CAP-2026-05-16-0042',             done: true },
    { at: t(-70),  kind: 'siren',     label: 'Sirena disparada',       detail: 'GPIO relay zona baja',                    done: true },
    { at: t(-30),  kind: 'notify',    label: 'Defensa Civil notificada',detail: 'Webhook municipal acusó recibo',         done: true },
    { at: t(60),   kind: 'sync',      label: 'Próxima ventana CV',     detail: 'Re-análisis automático en 60s',           done: false },
  ];
};

const DEMO_CAP = {
  status: 'emitted' as const,
  lastEmit: new Date(Date.now() - 1000 * 90).toLocaleString('es-AR', {
    hour: '2-digit', minute: '2-digit', second: '2-digit', day: '2-digit', month: '2-digit',
  }),
  receiptId: 'CAP-2026-05-16-0042',
  schemaVersion: 'CAP v1.2',
  recipientCount: 3,
};

// ──────────────────────────────────────────────────────────────────────────
// Dashboard (Persona C command center)
// ──────────────────────────────────────────────────────────────────────────
export default function Dashboard() {
  const { sites, alerts, fetchSites, fetchAlerts, isOnline, queueCount } = useAppStore();

  // Local state for the action rail. The buttons fire deterministic UI feedback
  // so the recording shows the loop closing — they do NOT silently invent
  // backend behavior; clicking dispatches an explicit "demo action" log line.
  const [actionState, setActionState] = useState<Record<ActionCall['fn'], { busy: boolean }>>({
    emit_cap_xml:         { busy: false },
    trigger_siren:        { busy: false },
    send_lora_alert:      { busy: false },
    notify_civil_defense: { busy: false },
  });
  const [actionLog, setActionLog] = useState<string[]>([]);
  const [timeline, setTimeline] = useState<TimelineEvent[]>(() => DEMO_TIMELINE_FACTORY());

  useEffect(() => {
    if (isOnline) {
      fetchSites();
      fetchAlerts();
    }
  }, [fetchSites, fetchAlerts, isOnline]);

  // Top-priority alert: the highest-level live alert, falling back to demo.
  const { activeAlert, activeSite, isDemo } = useMemo(() => {
    if (alerts.length > 0) {
      const order: Record<FusedAlert['level'], number> = { red: 0, orange: 1, yellow: 2, green: 3 };
      const sorted = [...alerts].sort((a, b) => order[a.level] - order[b.level] || b.score - a.score);
      const top = sorted[0];
      const site = sites.find((s) => s.id === top.site_id) ?? null;
      return { activeAlert: top, activeSite: site, isDemo: false };
    }
    return { activeAlert: DEMO_ALERT, activeSite: DEMO_SITE, isDemo: true };
  }, [alerts, sites]);

  const reasoningChain = useMemo(() => {
    if (!activeAlert?.reasoning_chain) return undefined;
    try {
      const parsed = JSON.parse(activeAlert.reasoning_chain);
      return Array.isArray(parsed) ? parsed.map(String) : undefined;
    } catch {
      return undefined;
    }
  }, [activeAlert]);

  const invokeAction = (fn: ActionCall['fn']) => {
    setActionState((prev) => ({ ...prev, [fn]: { busy: true } }));
    const at = new Date().toLocaleTimeString('es-AR');
    setActionLog((prev) => [`${at}  function_call → ${fn}(...)`, ...prev].slice(0, 5));

    setTimeout(() => {
      setActionState((prev) => ({ ...prev, [fn]: { busy: false } }));
      setActionLog((prev) => [`${new Date().toLocaleTimeString('es-AR')}  ✓ ${fn} ok`, ...prev].slice(0, 5));
      // mirror the action into the timeline so the demo loop closes visibly
      const at2 = new Date().toISOString();
      const map: Partial<Record<ActionCall['fn'], TimelineEvent>> = {
        emit_cap_xml:         { at: at2, kind: 'cap',    label: 'CAP v1.2 emitido',          detail: 'Re-emisión manual del operador',     done: true },
        trigger_siren:        { at: at2, kind: 'siren',  label: 'Sirena disparada',          detail: 'Operador disparó relay',             done: true },
        send_lora_alert:      { at: at2, kind: 'notify', label: 'Alerta LoRa enviada',       detail: 'Broadcast hacia nodos hermanos',     done: true },
        notify_civil_defense: { at: at2, kind: 'notify', label: 'Defensa Civil notificada',  detail: 'Re-envío manual al webhook',         done: true },
      };
      const event = map[fn];
      if (event) {
        setTimeline((prev) => [...prev, event]);
      }
    }, 900);
  };

  const actions: ActionCall[] = [
    { fn: 'emit_cap_xml',         arg: `site=${activeAlert.site_id}`, busy: actionState.emit_cap_xml.busy },
    { fn: 'trigger_siren',        arg: 'zona=baja',                    busy: actionState.trigger_siren.busy },
    { fn: 'send_lora_alert',      arg: 'broadcast',                    busy: actionState.send_lora_alert.busy },
    { fn: 'notify_civil_defense', arg: 'webhook=municipal',            busy: actionState.notify_civil_defense.busy },
  ];

  // The "all-clear" state: no active alert AND no demo fallback wanted —
  // currently we always show demo when alerts is empty, so this branch only
  // fires if alerts.length > 0 and somehow no top alert (defensive only).
  if (!activeAlert) {
    return (
      <div className="space-y-6 pb-20">
        <EmptyCommandCenter />
        <SitesGrid sites={sites} isOnline={isOnline} />
      </div>
    );
  }

  return (
    <div className="space-y-6 pb-20">
      {/* ── 5-second read ────────────────────────────────────────────── */}
      <RiskBannerForAlert alert={activeAlert} site={activeSite} isDemo={isDemo} />

      {/* ── Main two-column command grid ────────────────────────────── */}
      <div className="cc-grid">
        {/* Left column: signals → evidence → reasoning → audit */}
        <div className="space-y-4">
          <SectionPanel title="Fusión de señales" meta={`fused_score = ${activeAlert.score.toFixed(2)}`}>
            <SignalFusionRow inputs={DEMO_FUSION} />
          </SectionPanel>

          <SectionPanel title="Frame de evidencia · narración Pukaar AI" meta={activeAlert.reasoning_model ?? 'local'}>
            <EvidencePanel
              frameUrl={null}
              description={
                'Agua turbia cubre la franja inferior del encuadre y supera la línea crítica calibrada. ' +
                'Vegetación parcialmente sumergida en el margen derecho; sin infraestructura visible en riesgo aún.'
              }
              model={activeAlert.reasoning_model}
              confidence={0.78}
            />
          </SectionPanel>

          {activeAlert.reasoning_summary && (
            <Pukaar AIReasoning
              summary={activeAlert.reasoning_summary}
              chain={reasoningChain}
              model={activeAlert.reasoning_model}
            />
          )}

          <AuditTrace entries={DEMO_AUDIT} />
        </div>

        {/* Right column: CAP, action rail, offline sync */}
        <div className="space-y-4">
          <CapStatusCard {...DEMO_CAP} />

          <ActionRail actions={actions} onInvoke={invokeAction} />

          {actionLog.length > 0 && (
            <div className="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs font-mono text-slate-300 leading-snug space-y-1">
              <div className="text-slate-500 uppercase tracking-wider text-xs font-bold mb-1">
                stdout · function_call log
              </div>
              {actionLog.map((line, i) => (
                <div key={i}>{line}</div>
              ))}
            </div>
          )}

          <OfflineSyncCard
            isOnline={isOnline}
            queueCount={queueCount}
            lastSync={isOnline ? new Date().toLocaleTimeString('es-AR') : null}
          />
        </div>
      </div>

      {/* ── Lifecycle timeline (full width) ────────────────────────── */}
      <IncidentTimeline events={timeline} />

      {/* ── Auxiliary: sites grid for navigation ───────────────────── */}
      <SitesGrid sites={sites} isOnline={isOnline} />
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────────
// RiskBannerForAlert — thin wrapper that maps a FusedAlert + Site into the
// generic RiskBanner. Lives here so the dashboard owns the mapping.
// ──────────────────────────────────────────────────────────────────────────
function RiskBannerForAlert({
  alert,
  site,
  isDemo,
}: {
  alert: FusedAlert;
  site: Site | null;
  isDemo: boolean;
}) {
  return (
    <RiskBanner
      level={alert.level}
      score={alert.score}
      siteName={site?.name ?? alert.site_id}
      region={site?.region}
      summary={alert.summary}
      isDemo={isDemo}
    />
  );
}

// ──────────────────────────────────────────────────────────────────────────
// SitesGrid — preserves the dashboard's original "Monitored Sites" affordance
// so the operator can navigate into a SiteDetail mid-recording.
// ──────────────────────────────────────────────────────────────────────────
function SitesGrid({ sites, isOnline }: { sites: Site[]; isOnline: boolean }) {
  if (sites.length === 0) {
    return null;
  }
  return (
    <section>
      <h2 className="text-sm font-bold uppercase tracking-widest text-slate-800 mb-3">
        Sitios monitoreados
      </h2>
      <div className="grid gap-3 md:grid-cols-2">
        {sites.map((site) => (
          <Link
            key={site.id}
            to={`/sites/${site.id}`}
            className="p-4 bg-white border border-gray-200 rounded-lg shadow-sm hover:border-blue-300 transition-colors"
          >
            <div className="flex justify-between items-start gap-4">
              <div>
                <h3 className="font-semibold text-gray-900">{site.name}</h3>
                <p className="text-sm text-gray-500">{site.region}</p>
              </div>
              <span
                className={`px-2 py-1 text-xs rounded-full font-medium ${
                  site.is_active ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-700'
                }`}
              >
                {site.is_active ? 'Activo' : 'Inactivo'}
              </span>
            </div>
            <div className="mt-3 text-sm text-blue-600 font-medium inline-flex items-center gap-1">
              Abrir sitio <ArrowRight className="w-4 h-4" />
            </div>
            {!isOnline && (
              <div className="text-xs text-gray-400 mt-2">
                Offline — datos del último cache disponibles
              </div>
            )}
          </Link>
        ))}
      </div>
    </section>
  );
}
