import { useT } from '../i18n';
import { useLiveStatus } from '../lib/live';

/**
 * "● Live push" when AppSync Events is connected, otherwise how often the page polls.
 * `live` (from usePoll) says whether this page's own channels are subscribed; without it
 * the pill reads the shared connection (header use), and hides when no page is listening.
 */
export function LivePill({ live, every = 15, header = false }: { live?: boolean; every?: number; header?: boolean }) {
  const { t } = useT();
  const st = useLiveStatus();
  if (header && (!st.configured || !st.inUse)) return null;
  const on = live ?? (st.status === 'live' && st.failed.length === 0);
  const state = on ? 'on' : st.status === 'connecting' ? 'connecting' : 'polling';
  const word =
    state === 'on' ? t('live.push.on') : state === 'connecting' ? t('live.push.connecting') : t('live.push.polling', { s: every });
  return (
    <span
      className={`livepill is-${state}${header ? ' in-header' : ''}`}
      role="status"
      title={on ? t('live.push.title.on') : t('live.push.title.polling', { s: every })}
    >
      <span className="livepill-dot" aria-hidden="true" />
      <span className="livepill-word">{word}</span>
    </span>
  );
}
