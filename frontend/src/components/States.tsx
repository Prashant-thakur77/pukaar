import { CircleX, Lock, RotateCcw, Sparkles } from 'lucide-react';
import type { ReactNode } from 'react';
import { ApiError } from '../api';
import { useT } from '../i18n';

export function Skeleton({ lines = 3, height, className = '' }: { lines?: number; height?: number; className?: string }) {
  if (height) return <div className={`skel ${className}`} style={{ height }} aria-hidden="true" />;
  return (
    <div className={`skel-stack ${className}`} aria-hidden="true">
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="skel skel-line" style={{ width: `${92 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  );
}

export function SkeletonCards({ n = 3 }: { n?: number }) {
  return (
    <div className="skel-cards" aria-busy="true" role="status" aria-label="Loading">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="card skel-card">
          <div className="skel skel-pill" />
          <Skeleton lines={2} />
        </div>
      ))}
    </div>
  );
}

export function EmptyState({ title, body, icon, action }: { title: string; body?: string; icon?: ReactNode; action?: ReactNode }) {
  return (
    <div className="state state-empty">
      <div className="state-icon" aria-hidden="true">
        {icon ?? <Sparkles />}
      </div>
      <p className="state-title">{title}</p>
      {body && <p className="state-body">{body}</p>}
      {action}
    </div>
  );
}

export function ErrorState({ error, onRetry, compact }: { error: ApiError | null; onRetry?: () => void; compact?: boolean }) {
  const { t, lang } = useT();
  if (error?.isDenied) return <DeniedNote error={error} />;
  const detail = error && !error.isNetwork ? (lang === 'hi' && error.messageHi) || error.messageEn : null;
  return (
    <div className={`state state-error${compact ? ' is-compact' : ''}`} role="alert">
      <div className="state-icon" aria-hidden="true">
        <CircleX />
      </div>
      <p className="state-title">{error?.status === 404 ? t('state.empty') : t('state.error.title')}</p>
      <p className="state-body">{detail ?? t('state.error.body')}</p>
      {onRetry && (
        <button type="button" className="btn btn-ghost" onClick={onRetry}>
          <RotateCcw aria-hidden="true" /> {t('state.retry')}
        </button>
      )}
    </div>
  );
}

/** Readable denial from a 403 (Cedar policy reason). */
export function DeniedNote({ error }: { error: ApiError }) {
  const { t } = useT();
  return (
    <div className="denied" role="alert">
      <Lock aria-hidden="true" />
      <div>
        <p className="denied-title">{t('state.denied')}</p>
        <p className="denied-body">{error.messageEn}</p>
        {error.messageHi && (
          <p className="denied-body" lang="hi">
            {error.messageHi}
          </p>
        )}
        {error.code && <code className="denied-code">{error.code}</code>}
      </div>
    </div>
  );
}
