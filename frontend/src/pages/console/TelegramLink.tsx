import { useState } from 'react';
import { Check, Copy, LoaderCircle, Send } from 'lucide-react';
import { api, ApiError } from '../../api';
import { DeniedNote, ErrorState } from '../../components/States';
import { useT } from '../../i18n';
import type { TelegramLink as Link } from '../../types';

/** One-time code so this officer receives approval links in Telegram. */
export function TelegramLink() {
  const { t } = useT();
  const [link, setLink] = useState<Link | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [copied, setCopied] = useState(false);

  async function make() {
    setBusy(true);
    setErr(null);
    setCopied(false);
    try {
      setLink(await api.telegramLink());
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(false);
    }
  }

  async function copy() {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link.command);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="tg stack">
      <p className="small muted">{t('console.tg.lead')}</p>
      {link ? (
        <div className="tg-cmd">
          <code>{link.command}</code>
          <button type="button" className="icon-btn" onClick={copy} aria-label={t('common.copy')}>
            {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />}
          </button>
        </div>
      ) : null}
      {link && <p className="small muted">{t('console.tg.expires', { m: Math.max(1, Math.round(link.expires_in_seconds / 60)) })}</p>}
      <button type="button" className="btn btn-ghost btn-press" onClick={() => void make()} disabled={busy}>
        {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <Send aria-hidden="true" />} {t('console.tg.make')}
      </button>
      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
    </div>
  );
}
