import { useState } from 'react';
import { BellRing, ChevronDown } from 'lucide-react';
import { ApiError } from '../api';
import { usePoll } from '../hooks/usePoll';
import { useT } from '../i18n';
import { reasonWord, signalsLine } from '../lib/deviceHealth';
import { fmtTime } from '../lib/format';
import {
  audibleAllowed,
  healthChip,
  measText,
  readSoundReply,
  requestId,
  rowStatusWord,
  rowTone,
  sirenApi,
  smsLink,
  st,
  tierSummary,
  type AlertSirenFields,
  type SirenRow,
} from '../lib/sirens';
import type { Lang } from '../store';
import { ConfirmDialog } from './ConfirmDialog';
import '../sirens.css';

interface AlertLike extends AlertSirenFields {
  id: string;
  village_id: string;
  village_name: string;
  village_name_hi: string;
  level: string;
}

function errText(e: unknown, lang: Lang): string {
  if (e instanceof ApiError) return (lang === 'hi' && e.messageHi) || e.messageEn;
  return st(lang, 'error');
}

/**
 * The siren tier of one alert in the console: "Sirens 1/1 verified", the rows (commanded -> started ->
 * verified, with the device's own evidence) and the buttons Cedar allows for this officer or pradhan
 * (GET /villages/{id}/devices `can`). The public demo accounts see the tier and never get a button.
 */
export function SirenPanel({ alert }: { alert: AlertLike }) {
  const { lang } = useT();
  const [open, setOpen] = useState(false);
  const summary = tierSummary(alert, lang);
  const relevant = Boolean(summary) || alert.level === 'warning' || alert.level === 'critical';
  if (!relevant) return null;
  return (
    <div className="siren-panel">
      {summary && (
        <p className={`siren-tier small ${(alert.sirens_verified ?? 0) >= (alert.sirens_total ?? 0) ? 'ok-text' : 'bad-text'}`}>
          <BellRing aria-hidden="true" /> {summary}
        </p>
      )}
      <button type="button" className="trace-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {st(lang, 'tier.toggle')}
        <ChevronDown aria-hidden="true" className={open ? 'rot' : ''} />
      </button>
      {open && <SirenDetail alert={alert} />}
    </div>
  );
}

function SirenDetail({ alert }: { alert: AlertLike }) {
  const { lang } = useT();
  const tier = usePoll(() => sirenApi.alertSirens(alert.id), [alert.id], 15000);
  const devs = usePoll(() => sirenApi.villageDevices(alert.village_id), [alert.village_id], 30000);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<null | 'warning' | 'critical' | 'stop'>(null);
  const [sms, setSms] = useState<{ text: string; href: string } | null>(null);
  const village = lang === 'hi' ? alert.village_name_hi : alert.village_name;
  const can = devs.data?.can ?? { test_siren: false, sound_siren: false, stop_siren: false };
  const sirens = (devs.data?.devices ?? []).filter((d) => d.kind === 'siren');
  const requests = devs.data?.requests ?? [];
  const audible = audibleAllowed();

  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    setErr(null);
    setMsg(null);
    try {
      setMsg(await fn());
      await Promise.all([tier.refresh(), devs.refresh()]);
    } catch (e) {
      setErr(errText(e, lang));
    } finally {
      setBusy(false);
    }
  };

  const reason = st('en', 'reason.manual');
  const sound = (level: 'warning' | 'critical') =>
    run(async () => {
      const out = readSoundReply(await sirenApi.sound(alert.village_id, level, reason));
      return out.kind === 'needs_second'
        ? st(lang, 'reply.second', { t: fmtTime(out.expiresAt, lang) })
        : st(lang, 'reply.commanded', { n: out.n, p: out.pattern });
    });
  const stop = () =>
    run(async () => st(lang, 'reply.stopped', { n: (await sirenApi.stop(alert.village_id, reason)).stopped }));
  const test = (deviceId: string, kind: 'silent' | 'audible') =>
    run(async () => st(lang, 'reply.test', { p: (await sirenApi.test(deviceId, kind, reason)).pattern }));
  const confirm = (rid: string) =>
    run(async () => {
      const out = await sirenApi.confirm(rid);
      return st(lang, 'reply.commanded', { n: out.commanded, p: out.pattern });
    });
  const smsFor = (row: SirenRow) =>
    run(async () => {
      const out = await sirenApi.smsFallback(row.device_id, row.cmd_id);
      setSms({ text: out.text, href: out.sms_uri || smsLink(out.sim_number, out.text) });
      return st(lang, 'sms.text');
    });

  const rows = tier.data?.rows ?? [];
  return (
    <div className="siren-panel">
      {tier.error && !tier.data ? (
        <p className="small bad-text">{errText(tier.error, lang)}</p>
      ) : rows.length === 0 ? (
        <p className="small muted">{st(lang, 'tier.none')}</p>
      ) : (
        <ul className="siren-rows">
          {rows.map((r) => {
            const tone = rowTone(r.status);
            const meas = measText(r.meas);
            return (
              <li key={`${r.device_id}-${r.round}`}>
                <strong>{r.device_id}</strong>
                <span className="chip">{r.pattern}</span>
                <span className={`chip ${tone === 'good' ? 'chip-good' : tone === 'bad' ? 'chip-bad' : 'chip-pending'}`}>
                  {rowStatusWord(r.status, lang)}
                </span>
                <span className="small muted">
                  {r.commanded_at && `${st(lang, 'row.commanded')} ${fmtTime(r.commanded_at, lang)}`}
                  {r.started_at && ` → ${st(lang, 'row.started')} ${fmtTime(r.started_at, lang)}`}
                  {r.verified_at && ` → ${st(lang, 'row.verified')} ${fmtTime(r.verified_at, lang)}`}
                </span>
                {meas && <span className="small">{meas}</span>}
                {r.simulated && <span className="chip chip-replay">{st(lang, 'simulated')}</span>}
                {r.error && <span className="small bad-text">{r.error}</span>}
                {can.sound_siren && r.status !== 'verified' && r.cmd_id && (
                  <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => void smsFor(r)}>
                    {st(lang, 'btn.sms')}
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {(devs.data?.devices ?? []).some((d) => d.health !== 'ok') && (
        <ul className="siren-rows siren-health" aria-label={lang === 'hi' ? 'उपकरणों की सेहत' : 'Device health'}>
          {(devs.data?.devices ?? [])
            .filter((d) => d.health !== 'ok')
            .map((d) => {
              const chip = healthChip(d.health, lang);
              const line = signalsLine(d.health_signals, lang);
              return (
                <li key={`h-${d.device_id}`}>
                  <strong>{d.device_id}</strong>
                  <span className={`chip ${chip.cls}`}>{chip.label}</span>
                  <span className="small">
                    {[...(d.health_reasons ?? []).map((r) => reasonWord(r, lang)), line].filter(Boolean).join(' · ')}
                  </span>
                </li>
              );
            })}
        </ul>
      )}

      {requests.map((q) => (
        <p key={requestId(q)} className="small siren-actions">
          <span>{st(lang, 'request.open', { t: fmtTime(q.expires_at ?? null, lang) })}</span>
          {can.sound_siren && requestId(q) && (
            <button type="button" className="btn btn-sm" disabled={busy} onClick={() => void confirm(requestId(q))}>
              {st(lang, 'btn.confirm')}
            </button>
          )}
        </p>
      ))}

      {can.test_siren &&
        sirens.map((d) => (
          <div key={d.device_id} className="siren-actions" role="group" aria-label={d.device_id}>
            <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => void test(d.device_id, 'silent')}>
              {st(lang, 'btn.test.silent')}
            </button>
            <button
              type="button"
              className="btn btn-sm btn-ghost"
              disabled={busy || !audible}
              title={audible ? undefined : st(lang, 'btn.test.window')}
              onClick={() => void test(d.device_id, 'audible')}
            >
              {st(lang, 'btn.test.audible')}
            </button>
            {!audible && <span className="small muted">{st(lang, 'btn.test.window')}</span>}
          </div>
        ))}

      {(can.sound_siren || can.stop_siren) && (
        <div className="siren-actions">
          {can.sound_siren && (
            <>
              <button type="button" className="btn btn-sm" disabled={busy} onClick={() => setConfirming('warning')}>
                {st(lang, 'btn.sound.warning')}
              </button>
              <button type="button" className="btn btn-sm btn-danger" disabled={busy} onClick={() => setConfirming('critical')}>
                {st(lang, 'btn.sound.critical')}
              </button>
            </>
          )}
          {can.stop_siren && (
            <button type="button" className="btn btn-sm btn-ghost" disabled={busy} onClick={() => setConfirming('stop')}>
              {st(lang, 'btn.stop')}
            </button>
          )}
        </div>
      )}

      <p className="small" role="status" aria-live="polite">
        {msg}
      </p>
      {err && (
        <p className="small bad-text" role="alert">
          {err}
        </p>
      )}
      {sms && (
        <div className="siren-sms">
          <code>{sms.text}</code>
          <a className="link" href={sms.href}>
            {st(lang, 'sms.open')}
          </a>
        </div>
      )}

      {confirming && (
      <ConfirmDialog
        open
        title={st(lang, confirming === 'stop' ? 'confirm.stop.title' : 'confirm.sound.title', { village })}
        confirmLabel={
          confirming === 'stop' ? st(lang, 'btn.stop') : confirming === 'critical' ? st(lang, 'btn.sound.critical') : st(lang, 'btn.sound.warning')
        }
        cancelLabel={lang === 'hi' ? 'रद्द करें' : 'Cancel'}
        tone="danger"
        busy={busy}
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          const what = confirming;
          setConfirming(null);
          if (what === 'stop') void stop();
          else if (what) void sound(what);
        }}
      >
        <p>{st(lang, confirming === 'stop' ? 'confirm.stop.body' : 'confirm.sound.body')}</p>
      </ConfirmDialog>
      )}
    </div>
  );
}
