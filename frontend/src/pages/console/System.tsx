import { ErrorState, Skeleton } from '../../components/States';
import type { PollState } from '../../hooks/usePoll';
import { useT, type Key } from '../../i18n';
import type { Health } from '../../types';

type Tone = 'good' | 'warn' | 'bad';

/** Reads a /health service string ("ok", "unavailable locally: text only", …) as a status. */
function serviceTone(v: unknown): Tone {
  const s = String(v ?? '').toLowerCase();
  if (!s) return 'warn';
  if (/(error|fail|down|unreachable)/.test(s)) return 'bad';
  if (/(unavailable|disabled|not configured|stub|fallback|mock|local)/.test(s)) return 'warn';
  return 'good';
}

function Row({ label, value, tone }: { label: string; value: string; tone: Tone }) {
  const { t } = useT();
  return (
    <div className="sys-row">
      <dt>{label}</dt>
      <dd>
        <span className={`sys-dot is-${tone}`} aria-hidden="true" />
        <span className="sr-only">{t(`system.tone.${tone}` as Key)}: </span>
        {value}
      </dd>
    </div>
  );
}

export function SystemCard({ poll }: { poll: PollState<Health> }) {
  const { t } = useT();
  const h = poll.data;
  if (poll.loading && !h) return <Skeleton lines={4} />;
  if (poll.error && !h) return <ErrorState error={poll.error} onRetry={poll.refresh} compact />;
  if (!h) return null;
  const sv = h.services ?? {};
  const local = h.mode === 'local';
  const str = (v: unknown) => (v == null || v === '' ? t('common.unknown') : String(v));
  const bedrock = str(sv.bedrock);
  return (
    <dl className="sys-list">
      <Row label={t('system.mode')} value={local ? t('system.mode.local') : t('system.mode.aws')} tone={local ? 'warn' : 'good'} />
      <Row label={t('system.workflow')} value={str(h.workflow)} tone={/step functions/i.test(String(h.workflow)) && !local ? 'good' : serviceTone(h.workflow ?? (local ? 'local' : ''))} />
      <Row label={t('system.model')} value={`${h.model ?? t('common.unknown')} · ${bedrock}`} tone={serviceTone(sv.bedrock)} />
      <Row label="Polly" value={str(sv.polly)} tone={serviceTone(sv.polly)} />
      <Row label="Transcribe" value={str(sv.transcribe)} tone={serviceTone(sv.transcribe)} />
      <Row label="Telegram" value={str(sv.telegram)} tone={serviceTone(sv.telegram)} />
    </dl>
  );
}
