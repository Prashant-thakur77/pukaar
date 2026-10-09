import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, Pause, Volume2, VolumeX } from 'lucide-react';
import { api } from '../api';
import { useT } from '../i18n';

/** Plays the server-made Polly MP3 for an alert. Never synthesises client text. */
export function ListenButton({ alertId, big, hasAudio }: { alertId: string; big?: boolean; hasAudio?: boolean }) {
  const { t } = useT();
  const [state, setState] = useState<'idle' | 'loading' | 'playing' | 'none'>('idle');
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => () => audio.current?.pause(), []);

  if (hasAudio === false)
    return (
      <span className="chip chip-muted" role="note">
        <VolumeX aria-hidden="true" /> {t('common.audio.text')}
      </span>
    );

  async function toggle() {
    if (state === 'playing') {
      audio.current?.pause();
      setState('idle');
      return;
    }
    setState('loading');
    try {
      if (!audio.current) {
        const res = await api.alertAudio(alertId);
        if (!res.url) {
          setState('none');
          return;
        }
        const a = new Audio(res.url);
        a.onended = () => setState('idle');
        a.onerror = () => setState('none');
        audio.current = a;
      }
      await audio.current.play();
      setState('playing');
    } catch {
      setState('none');
    }
  }

  return (
    <span className="listen">
      <button
        type="button"
        className={`btn ${big ? 'btn-lg' : 'btn-sm'} btn-listen${state === 'playing' ? ' is-playing' : ''}`}
        onClick={toggle}
        aria-label={state === 'playing' ? 'आवाज़ रोकें (Pause)' : 'चेतावनी सुनें (Listen to the Hindi alert)'}
        aria-pressed={state === 'playing'}
      >
        {state === 'loading' ? <LoaderCircle className="spin" aria-hidden="true" /> : state === 'playing' ? <Pause aria-hidden="true" /> : <Volume2 aria-hidden="true" />}
        <span lang="hi">सुनें</span>
        {state === 'playing' && <span className="eq" aria-hidden="true"><i /><i /><i /></span>}
      </button>
      {state === 'none' && <span className="muted small" role="status">{t('common.audio.none')}</span>}
    </span>
  );
}
