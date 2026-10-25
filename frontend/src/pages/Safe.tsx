import { useParams } from 'react-router-dom';
import { CircleAlert, Phone, ShieldCheck } from 'lucide-react';
import { api } from '../api';
import { Skeleton } from '../components/States';
import { usePoll } from '../hooks/usePoll';
import { useT, type Key } from '../i18n';
import '../styles/Safe.css';

/** One line in the page's language (the header's switch changes it). */
function Line({ k, vars, as: Tag = 'p', className = '' }: { k: Key; vars?: Record<string, string>; as?: 'p' | 'h1' | 'span'; className?: string }) {
  const { t } = useT();
  return <Tag className={className}>{t(k, vars)}</Tag>;
}

/** Times are shown in India time, where the village is, and say so. */
function clockIST(iso: string): string {
  return new Intl.DateTimeFormat('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }).format(new Date(iso));
}
function dayIST(iso: string, locale: string): string {
  return new Intl.DateTimeFormat(locale, { day: 'numeric', month: 'long', timeZone: 'Asia/Kolkata' }).format(new Date(iso));
}

/**
 * /safe/:token — the family link from the roll-call. Shows only a first name (or "Your family member"),
 * the time and the village: no phone number, no location beyond the village.
 */
export default function Safe() {
  const { t, lang } = useT();
  const { token = '' } = useParams();
  const { data, error, loading } = usePoll(() => api.safe(token), [token], 0);

  if (loading && !data)
    return (
      <div className="safe-page">
        <div className="safe-card">
          <Skeleton lines={4} />
        </div>
      </div>
    );

  if (error || !data) {
    const code = error?.code;
    const [title, body]: [Key, Key] =
      code === 'expired' ? ['safe.expired', 'safe.expired.body'] : code === 'not_current' ? ['safe.changed', 'safe.changed.body'] : ['safe.invalid', 'safe.invalid.body'];
    return (
      <div className="safe-page">
        <WaterLines />
        <div className="safe-card is-quiet" role="alert">
          <CircleAlert className="safe-icon-quiet" aria-hidden="true" />
          <Line k={title} as="h1" className="safe-title-sm" />
          <Line k={body} className="safe-why" />
          <Call112 />
        </div>
      </div>
    );
  }

  const name = data.first_name;
  const at = clockIST(data.at);
  return (
    <div className="safe-page">
      <WaterLines />
      <article className="safe-card" aria-labelledby="safe-h">
        <p className="safe-eyebrow">{t('safe.eyebrow')}</p>
        <div className="safe-mark" aria-hidden="true">
          <span className="safe-ring" />
          <ShieldCheck />
        </div>
        <h1 id="safe-h" className="safe-title">
          {name ?? t('safe.someone')} {t('safe.marked')}
        </h1>
        <p className="safe-when">
          <time dateTime={data.at}>{at}</time>
          <span className="safe-sep" aria-hidden="true">·</span>
          <span>{lang === 'hi' ? data.village_name_hi || data.village_name : data.village_name}</span>
        </p>
        <p className="safe-date">
          {dayIST(data.at, lang === 'hi' ? 'hi-IN' : 'en-IN')} · IST
        </p>
        {data.exercise && <Line k="safe.exercise" className="safe-flag" />}
        {data.simulated && <Line k="safe.simulated" className="safe-flag" />}
        <Line k="safe.why" className="safe-why" />
        <Line k="safe.privacy" className="safe-privacy" />
        <Call112 />
      </article>
    </div>
  );
}

function Call112() {
  const { t } = useT();
  return (
    <a className="safe-112" href="tel:112">
      <Phone aria-hidden="true" />
      <span>{t('safe.call112')}</span>
    </a>
  );
}

/** Slow river lines behind the card; still under reduced motion. */
function WaterLines() {
  return (
    <svg className="safe-water" viewBox="0 0 1200 400" preserveAspectRatio="none" aria-hidden="true" focusable="false">
      <path className="sw sw-1" d="M0 260 C 200 220, 400 300, 600 260 S 1000 220, 1200 260" />
      <path className="sw sw-2" d="M0 300 C 220 270, 420 340, 640 300 S 1020 270, 1200 300" />
      <path className="sw sw-3" d="M0 340 C 240 320, 460 370, 680 340 S 1040 320, 1200 340" />
    </svg>
  );
}
