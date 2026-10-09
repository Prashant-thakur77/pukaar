#!/usr/bin/env node
// Dev-only mock of the Pukaar API (docs/CONTRACT.md shapes) for visual checks.
// EVERYTHING HERE IS SAMPLE DATA: every response carries "_sample": true and the
// UI shows a "SAMPLE DATA" ribbon. Never deploy this. Run: npm run mock
import http from 'node:http';

const PORT = Number(process.env.MOCK_PORT ?? 8787);
const now = Date.now();
const iso = (msAgo) => new Date(now - msAgo).toISOString();
const H = 3600e3;

// Coordinates are the Open-Meteo grid points in data/probes (not verified).
const VILLAGES = [
  { id: 'thunag', name: 'Thunag', name_hi: 'थुनाग', lat: 31.575, lon: 77.175, level: 'critical', base: 160 },
  { id: 'gohar', name: 'Gohar', name_hi: 'गोहर', lat: 31.575, lon: 77.025, level: 'warning', base: 110 },
  { id: 'janjehli', name: 'Janjehli', name_hi: 'जंजैहली', lat: 31.525, lon: 77.225, level: 'watch', base: 70 },
  { id: 'pandoh', name: 'Pandoh', name_hi: 'पंडोह', lat: 31.675, lon: 77.075, level: 'normal', base: 30 },
  { id: 'karsog', name: 'Karsog', name_hi: 'करसोग', lat: 31.385, lon: 77.2, level: 'normal', base: 18 },
];
const RAIN_BANDS = { critical: 204.5, warning: 115.6, watch: 64.5 };
const LEVELS = ['normal', 'watch', 'warning', 'critical'];
const rainLevel = (mm) => (mm >= 204.5 ? 'critical' : mm >= 115.6 ? 'warning' : mm >= 64.5 ? 'watch' : 'normal');
const thresholds = (v) => ({ watch: 180 + v.base * 0.2, warning: 260 + v.base * 0.3, critical: 340 + v.base * 0.4, source: 'SAMPLE thresholds' });

function readings(v) {
  return Array.from({ length: 48 }, (_, i) => {
    const t = 47 - i;
    const ramp = Math.max(0, 1 - t / 40);
    const rain = Math.round((v.base * (0.25 + 0.95 * ramp) + 6 * Math.sin(i / 3)) * 10) / 10;
    const th = thresholds(v);
    const dis = Math.round((th.watch * 0.55 + (th.critical * 1.05 - th.watch * 0.55) * ramp * (v.base / 160)) * 10) / 10;
    return {
      village_id: v.id,
      at: iso(t * 0.5 * H),
      rain_24h_mm: rain,
      rain_hourly: Array.from({ length: 6 }, (_, k) => ({ t: iso((t * 0.5 + 6 - k) * H), mm: Math.round(rain / 24 + k) })),
      discharge: dis,
      discharge_forecast: [],
      discharge_peak: Math.round(dis * 1.08 * 10) / 10,
      rain_level: rainLevel(rain),
      river_level: dis >= th.critical ? 'critical' : dis >= th.warning ? 'warning' : dis >= th.watch ? 'watch' : 'normal',
      source: 'replay',
      replay: true,
    };
  });
}

const READINGS = Object.fromEntries(VILLAGES.map((v) => [v.id, readings(v)]));

function village(v) {
  const r = READINGS[v.id];
  return {
    id: v.id,
    name: v.name,
    name_hi: v.name_hi,
    district: 'Mandi',
    lat: v.lat,
    lon: v.lon,
    coords_verified: false,
    population: null,
    level: v.level,
    level_since: iso(v.level === 'critical' ? 1.2 * H : 5 * H),
    calm_sweeps: 0,
    thresholds: thresholds(v),
    latest_reading: r[r.length - 1],
    open_alert_id: alerts.find((a) => a.village_id === v.id && ['pending', 'approved', 'delivering'].includes(a.status))?.id ?? null,
  };
}

function trace(v) {
  const r = READINGS[v.id].at(-1);
  const rules = [];
  if (r.rain_level !== 'normal') rules.push(`rain_24h>=${RAIN_BANDS[r.rain_level]}mm:${r.rain_level}`);
  if (r.river_level !== 'normal') rules.push(`discharge>=${thresholds(v)[r.river_level]}:${r.river_level}`);
  if (r.rain_level !== 'normal' && r.river_level !== 'normal') rules.push('two_sources_agree:+1');
  return {
    level: v.level,
    rain_level: r.rain_level,
    river_level: r.river_level,
    report_level: 'normal',
    rules_fired: rules,
    contradictions: v.id === 'gohar' ? ['data_high_reports_low'] : [],
    rules_version: 'risk-rules-v1',
    evidence: [
      { kind: 'reading', at: r.at, source: 'replay', rain_24h_mm: r.rain_24h_mm, rain_level: r.rain_level, rain_bands_mm: RAIN_BANDS, discharge_peak: r.discharge_peak, river_level: r.river_level, thresholds: thresholds(v), replay: true },
      ...(v.id === 'thunag' ? [{ kind: 'report', report_id: 'r1', at: iso(0.6 * H), type: 'water_rising', severity: 'high', state: 'verified_auto', verified: true, weight: 1, replay: false }] : []),
    ],
  };
}

let seq = 100;
const alerts = [
  mkAlert('a1', VILLAGES[0], 'pending', 'warning', 0.4, 'bedrock:anthropic.claude-haiku'),
  mkAlert('a2', VILLAGES[1], 'pending', 'watch', 0.9, 'rule-fallback', false),
  mkAlert('a3', VILLAGES[1], 'delivered', 'normal', 6, 'bedrock:anthropic.claude-haiku', true, 38, 21),
  mkAlert('a4', VILLAGES[2], 'auto_sent_unapproved', 'normal', 12, 'bedrock:anthropic.claude-haiku', true, 12, 4),
];

function mkAlert(id, v, status, prev, hoursAgo, model, check = true, delivered = 0, acked = 0) {
  const hi = {
    critical: `${v.name_hi} के लोग ध्यान दें: नदी का पानी तेज़ी से बढ़ रहा है। अभी ऊँची जगह पर जाएँ। नदी और नालों से दूर रहें। मदद के लिए 112 पर कॉल करें।`,
    warning: `${v.name_hi}: अगले 6 घंटे में भारी बारिश और नदी का पानी बढ़ने की आशंका है। ज़रूरी सामान तैयार रखें। नदी किनारे न जाएँ।`,
    watch: `${v.name_hi}: बारिश बढ़ रही है। नदी पर नज़र रखें और अगली सूचना का इंतज़ार करें।`,
  }[v.level];
  const en = {
    critical: `People of ${v.name}: river water is rising fast. Move to high ground now. Stay away from the river and streams. Call 112 for help.`,
    warning: `${v.name}: heavy rain and rising river expected in the next 6 hours. Keep essentials ready. Do not go near the riverbank.`,
    watch: `${v.name}: rain is increasing. Keep an eye on the river and wait for the next update.`,
  }[v.level];
  const approved = ['approved', 'delivering', 'delivered', 'closed'].includes(status);
  return {
    id, village_id: v.id, village_name: v.name, village_name_hi: v.name_hi, level: v.level, previous_level: prev, status,
    created_at: iso(hoursAgo * H), updated_at: iso(hoursAgo * H * 0.5), text_hi: hi, text_en: en,
    reason_en: `24 h rain ${READINGS[v.id].at(-1).rain_24h_mm} mm and forecast discharge peak ${READINGS[v.id].at(-1).discharge_peak} m³/s.`,
    reasoning_model: model, draft_check: check ? { passed: true, reason: 'Names the place, level, action and 112.' } : { passed: false, reason: 'Model unavailable; fixed Hindi template used.' },
    decision_trace: trace(v), recipients_count: 40 + v.base / 4 | 0, officer_index: 0, decided_by: approved ? 'officer1' : null,
    decided_at: approved ? iso(hoursAgo * H * 0.8) : null, approved, delivered_count: delivered, acknowledged_count: acked, replay: true,
  };
}

const reports = [
  mkReport('r1', 'thunag', 'water_rising', 'high', 'verified_auto', 0.6, 'Stream has reached the lower bridge near the school.', 'स्कूल के पास निचले पुल तक नाले का पानी आ गया है।'),
  mkReport('r2', 'gohar', 'road_cut', 'medium', 'unverified', 1.5, 'Debris on the Gohar–Chail Chowk road; cars cannot pass.', 'गोहर चैलचौक सड़क पर मलबा है, गाड़ी नहीं जा सकती।'),
  mkReport('r3', 'janjehli', 'landslide', 'high', 'received', 0.2, 'Small landslide above the market, no one hurt.', 'बाज़ार के ऊपर छोटा भूस्खलन, कोई घायल नहीं।'),
];

function mkReport(id, vid, type, sev, state, hoursAgo, summary, transcript) {
  return {
    id, village_id: vid, created_at: iso(hoursAgo * H), text: '', transcript, report_type: type, severity: sev, summary_en: summary,
    reply_hi: 'आपकी सूचना मिल गई।', lat: null, lon: null, photo_url: null, audio_url: null, state, previous_state: null,
    parser_source: 'bedrock+keywords', flags: [], track_code: `PK${id.toUpperCase()}7Q`, replay: false,
  };
}

const directives = [
  { id: 'd1', village_id: 'thunag', type: 'evacuate', text_hi: 'थुनाग: नदी किनारे के घर खाली करें और स्कूल भवन में जाएँ।', text_en: 'Thunag: leave riverside homes and go to the school building.', issued_by: 'officer1', issued_at: iso(0.3 * H), active: true },
];
let replay = { active: true, available: true, clock: '2025-06-30T22:00:00+05:30', hours_total: 72, hours_done: 31, source: 'open-meteo archive (Mandi, 2025-06-28..07-01)' };
const audit = [
  { at: iso(0.3 * H), id: 'au1', actor: 'officer1', role: 'officer', action: 'directive.create', resource: 'd1', decision: 'allow', reason: 'officer may issue directives' },
  { at: iso(0.35 * H), id: 'au2', actor: 'pradhan_thunag', role: 'pradhan', action: 'alert.approve', resource: 'a1', decision: 'deny', reason: 'Policy officer-approves-alerts: only officers approve alerts' },
  { at: iso(6 * H), id: 'au3', actor: 'officer2', role: 'officer', action: 'alert.approve', resource: 'a3', decision: 'allow', reason: 'officer, alert pending, within window' },
];

function stamp(body) {
  if (Array.isArray(body)) return body.map((x) => (x && typeof x === 'object' ? { ...x, _sample: true } : x));
  if (body && typeof body === 'object') return { ...body, _sample: true };
  return body;
}

function send(res, status, body) {
  res.writeHead(status, {
    'Content-Type': 'application/json; charset=utf-8',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
  });
  res.end(JSON.stringify(status < 400 ? stamp(body) : body));
}

const readBody = (req) =>
  new Promise((resolve) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks);
      if ((req.headers['content-type'] ?? '').includes('json')) {
        try {
          resolve(JSON.parse(raw.toString() || '{}'));
          return;
        } catch {
          /* fallthrough */
        }
      }
      resolve({ _raw: raw.toString('latin1') });
    });
  });

const userOf = (req) => {
  const m = (req.headers.authorization ?? '').match(/^Bearer dev-(\w+)$/);
  if (!m) return null;
  return { username: m[1], role: m[1].startsWith('pradhan') ? 'pradhan' : 'officer', village_ids: m[1].startsWith('pradhan') ? ['thunag'] : [] };
};

const deny = (res, action) =>
  send(res, 403, {
    detail: {
      code: 'policy_denied',
      message_en: `Cedar policy "officer-approves-alerts" denied ${action}: a pradhan can view alerts but only a district officer can approve or decline them.`,
      message_hi: 'प्रधान चेतावनी देख सकते हैं, पर मंज़ूरी केवल ज़िला अधिकारी दे सकते हैं।',
    },
  });

const overview = () => ({
  counters: { villages_watched: VILLAGES.length, alerts_sent: alerts.filter((a) => a.delivered_count > 0).length, phones_acknowledged: alerts.reduce((s, a) => s + a.acknowledged_count, 0), reports_received: reports.length },
  villages: VILLAGES.map((v) => ({ id: v.id, name: v.name, name_hi: v.name_hi, lat: v.lat, lon: v.lon, level: v.level, coords_verified: false })),
  recent_alerts: alerts.map((a) => ({ id: a.id, village_name: a.village_name, village_name_hi: a.village_name_hi, level: a.level, status: a.status, created_at: a.created_at, approved: a.approved, delivered_count: a.delivered_count, acknowledged_count: a.acknowledged_count, replay: a.replay })),
  replay: { active: replay.active },
});

const server = http.createServer(async (req, res) => {
  if (req.method === 'OPTIONS') return send(res, 204, {});
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const p = url.pathname;
  const seg = p.split('/').filter(Boolean);
  const user = userOf(req);
  const needUser = () => {
    if (!user) send(res, 401, { detail: 'Sign in required' });
    return !!user;
  };
  const body = ['POST', 'PATCH'].includes(req.method) ? await readBody(req) : {};

  if (p === '/health') return send(res, 200, { status: 'ok', mode: 'local', services: { dynamodb: 'mock', bedrock: 'mock' }, replay_active: replay.active });
  if (p === '/auth/dev-login' && req.method === 'POST') {
    const u = body.username;
    if (!['officer1', 'officer2', 'pradhan_thunag'].includes(u)) return send(res, 400, { detail: 'Unknown demo user' });
    return send(res, 200, { token: `dev-${u}`, username: u, role: u.startsWith('pradhan') ? 'pradhan' : 'officer' });
  }
  if (p === '/me/telegram-link') return needUser() && send(res, 200, { code: 'K7Q2', command: '/link K7Q2', expires_in_seconds: 600 });
  if (p === '/me') return needUser() && send(res, 200, user);
  if (p === '/public/overview') return send(res, 200, overview());
  if (p === '/villages') return send(res, 200, VILLAGES.map(village));
  if (seg[0] === 'villages' && seg[1]) {
    const v = VILLAGES.find((x) => x.id === seg[1]);
    if (!v) return send(res, 404, { detail: 'Village not found' });
    return send(res, 200, {
      village: village(v),
      readings: READINGS[v.id],
      alerts: alerts.filter((a) => a.village_id === v.id),
      reports: reports.filter((r) => r.village_id === v.id),
      past_events: v.level === 'critical' ? [{ date: '2023-07-09', level: 'critical', text_en: 'SAMPLE: heavy-rain event; road and bridge damage reported.', text_hi: 'नमूना: भारी बारिश, सड़क और पुल को नुकसान।' }] : [],
      nowcast: v.level === 'normal' ? null : { likely_level: v.level, hours: 6, text_en: `Likely to stay at ${v.level} for the next 6 hours.`, text_hi: 'अगले 6 घंटे यही स्तर रहने की संभावना।' },
    });
  }
  if (p === '/alerts' && req.method === 'GET') {
    if (!needUser()) return;
    const st = url.searchParams.get('status');
    const vid = url.searchParams.get('village_id');
    return send(res, 200, alerts.filter((a) => (!st || a.status === st) && (!vid || a.village_id === vid)));
  }
  if (seg[0] === 'alerts' && seg[1]) {
    const a = alerts.find((x) => x.id === seg[1]);
    if (!a) return send(res, 404, { detail: 'Alert not found' });
    if (seg[2] === 'audio') return send(res, 200, { url: null, text_hi: a.text_hi });
    if (seg[2] === 'ack') return send(res, 200, { ok: true, acknowledged_at: new Date().toISOString() });
    if (!needUser()) return;
    if (seg[2] === 'approve' || seg[2] === 'decline') {
      if (user.role !== 'officer') return deny(res, `alert.${seg[2]}`);
      if (a.status !== 'pending') return send(res, 409, { detail: { code: 'late', message_en: 'Already decided by another officer.', message_hi: 'किसी और अधिकारी ने पहले ही फ़ैसला कर लिया है।' } });
      a.status = seg[2] === 'approve' ? 'delivering' : 'declined';
      a.approved = seg[2] === 'approve';
      a.decided_by = user.username;
      a.decided_at = new Date().toISOString();
      return send(res, 200, a);
    }
    return send(res, 200, {
      alert: a,
      deliveries: a.delivered_count ? [{ alert_id: a.id, recipient_id: 'tg1', name: 'Sample recipient', channel: 'stub', status: 'sent', sent_at: a.updated_at, attempts: 1, acknowledged_at: a.acknowledged_count ? a.updated_at : null, error: null }] : [],
      timeline: [
        { at: a.created_at, step: 'draft', detail: `drafted by ${a.reasoning_model}` },
        { at: a.created_at, step: 'ask_officer', detail: 'sent approval link to officer1' },
        ...(a.decided_at ? [{ at: a.decided_at, step: 'approved', detail: `by ${a.decided_by}` }] : []),
      ],
      audit: audit.filter((x) => x.resource === a.id),
    });
  }
  if (seg[0] === 'approval' && seg[1]) {
    const a = alerts[0];
    if (seg[1] === 'late') return send(res, 409, { detail: { code: 'late', message_en: 'This approval link was already used.', message_hi: 'यह लिंक पहले ही इस्तेमाल हो चुका है।' } });
    if (req.method === 'POST') {
      if (a.status !== 'pending') return send(res, 409, { detail: { code: 'late', message_en: 'Already decided.', message_hi: 'पहले ही फ़ैसला हो चुका है।' } });
      a.status = body.decision === 'approve' ? 'delivering' : 'declined';
      a.approved = body.decision === 'approve';
      return send(res, 200, a);
    }
    return send(res, 200, { alert: a, expires_at: new Date(Date.now() + 9 * 60e3).toISOString(), valid: a.status === 'pending' });
  }
  if (p === '/reports' && req.method === 'POST') {
    const vid = (body._raw?.match(/name="village_id"\r\n\r\n([^\r]+)/) ?? [])[1] ?? 'thunag';
    const r = mkReport(`r${++seq}`, vid, 'other', 'medium', 'received', 0, 'New report (sample).', '');
    r.track_code = `PK${seq}X`;
    reports.unshift(r);
    return send(res, 200, { report: r, track_code: r.track_code });
  }
  if (p === '/reports') return needUser() && send(res, 200, reports);
  if (seg[0] === 'reports' && seg[2] === 'state') {
    if (!needUser()) return;
    if (user.role !== 'officer') return deny(res, 'report.set_state');
    const r = reports.find((x) => x.id === seg[1]);
    if (!r) return send(res, 404, { detail: 'Report not found' });
    r.previous_state = r.state;
    r.state = body.state;
    return send(res, 200, r);
  }
  if (p === '/directives' && req.method === 'POST') {
    if (!needUser()) return;
    if (user.role !== 'officer') return deny(res, 'directive.create');
    const v = VILLAGES.find((x) => x.id === body.village_id);
    const d = { id: `d${++seq}`, village_id: body.village_id, type: body.type, text_hi: `${v?.name_hi ?? ''}: नया निर्देश (नमूना)।`, text_en: `${v?.name ?? ''}: ${body.type} (sample). ${body.note_en ?? ''}`, issued_by: user.username, issued_at: new Date().toISOString(), active: true };
    directives.unshift(d);
    return send(res, 200, d);
  }
  if (p === '/directives') return send(res, 200, directives);
  if (p === '/replay/status') return send(res, 200, replay);
  if (p === '/replay/start') return needUser() && send(res, 200, (replay = { ...replay, active: true }));
  if (p === '/replay/reset') return needUser() && send(res, 200, (replay = { ...replay, active: false, hours_done: 0, clock: null }));
  if (p === '/audit') {
    if (!needUser()) return;
    const r = url.searchParams.get('resource');
    return send(res, 200, audit.filter((x) => !r || x.resource === r));
  }
  if (p === '/stats') return needUser() && send(res, 200, { ...overview().counters, alerts_by_status: {}, levels: {} });
  if (p === '/track/' + seg[1] && seg[0] === 'track') {
    const r = reports.find((x) => x.track_code === seg[1]);
    if (!r) return send(res, 404, { detail: 'Unknown code' });
    const v = VILLAGES.find((x) => x.id === r.village_id);
    const verified = ['verified', 'verified_auto', 'reviewed', 'actioned', 'resolved'].includes(r.state);
    return send(res, 200, {
      code: r.track_code, village_name: v.name, village_name_hi: v.name_hi, created_at: r.created_at, report_type: r.report_type, state: r.state,
      steps: [
        { key: 'received', done: true, at: r.created_at },
        { key: 'verified', done: verified, at: verified ? iso(0.3 * H) : null },
        { key: 'acted_on', done: ['actioned', 'resolved'].includes(r.state), at: null },
      ],
    });
  }
  if (p === '/ask/officer') {
    if (!needUser()) return;
    const top = [...VILLAGES].sort((a, b) => READINGS[b.id].at(-1).rain_24h_mm - READINGS[a.id].at(-1).rain_24h_mm);
    return send(res, 200, {
      answer: `${top[0].name} and ${top[1].name} had the most rain in the last 24 hours (${READINGS[top[0].id].at(-1).rain_24h_mm} mm and ${READINGS[top[1].id].at(-1).rain_24h_mm} mm). ${top[0].name} is at Critical with one pending alert. (Sample answer.)`,
      chart: { type: 'bar', title: '24 h rainfall by village (sample)', x_label: 'Village', y_label: 'mm', series: [{ name: 'Rain 24 h', points: top.map((v) => ({ x: v.name, y: READINGS[v.id].at(-1).rain_24h_mm })) }] },
      map: { village_ids: [top[0].id, top[1].id], points: [] },
      tools: [
        { name: 'get_latest_readings', input: { village_ids: 'all' }, output_summary: `${VILLAGES.length} readings`, decision: 'allow' },
        { name: 'list_alerts', input: { status: 'pending' }, output_summary: '2 pending alerts', decision: 'allow' },
      ],
      model: 'bedrock:anthropic.claude-haiku (sample)',
    });
  }
  send(res, 404, { detail: `No mock for ${req.method} ${p}` });
});

server.listen(PORT, () => console.log(`Pukaar mock API (SAMPLE DATA) on http://localhost:${PORT}`));
