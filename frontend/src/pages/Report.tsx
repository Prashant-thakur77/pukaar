import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Camera, Check, CircleCheck, Copy, Hourglass, LoaderCircle, MapPin, Mic, PenLine, Send, Share2, Square, Trash2, X } from 'lucide-react';
import { api, ApiError } from '../api';
import { Call112 } from '../components/Shell';
import { LevelBadge } from '../components/Level';
import { useMediaRecorder } from '../hooks/useMediaRecorder';
import { useT } from '../i18n';
import { fmtAgo } from '../lib/format';
import { saveReportOffline, toPendingAttachment } from '../lib/idb';
import { compressPhoto } from '../lib/photo';
import { flushQueue, refreshQueueCount } from '../lib/queue';
import { myTrackCodes, readLS, rememberTrackCode, useNet, writeLS } from '../store';
import type { Level, Village } from '../types';

type CachedVillage = Pick<Village, 'id' | 'name' | 'name_hi' | 'level'>;
type Phase = { k: 'compose' } | { k: 'sending' } | { k: 'queued' } | { k: 'done'; code: string };

const MAX_MS = 20000;

function cachedVillages(): CachedVillage[] {
  try {
    const v = JSON.parse(readLS('pukaar.villages') ?? '[]') as CachedVillage[];
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export default function Report() {
  const { t, lang } = useT();
  const online = useNet((s) => s.online);
  const [villages, setVillages] = useState<CachedVillage[]>(cachedVillages);
  const [villageId, setVillageId] = useState(() => readLS('pukaar.myVillage') ?? '');
  const [text, setText] = useState('');
  const [writing, setWriting] = useState(false);
  const [photo, setPhoto] = useState<Blob | null>(null);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [gps, setGps] = useState<{ lat: number; lon: number; acc: number } | null>(null);
  const [gpsState, setGpsState] = useState<'idle' | 'busy' | 'fail'>('idle');
  const [phase, setPhase] = useState<Phase>({ k: 'compose' });
  const [err, setErr] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [mine, setMine] = useState(myTrackCodes);
  const rec = useMediaRecorder(MAX_MS);
  const fileRef = useRef<HTMLInputElement>(null);
  const textRef = useRef<HTMLTextAreaElement>(null);

  const photoUrl = useMemo(() => (photo ? URL.createObjectURL(photo) : null), [photo]);
  const audioUrl = useMemo(() => (rec.audioBlob ? URL.createObjectURL(rec.audioBlob) : null), [rec.audioBlob]);
  useEffect(() => () => void (photoUrl && URL.revokeObjectURL(photoUrl)), [photoUrl]);
  useEffect(() => () => void (audioUrl && URL.revokeObjectURL(audioUrl)), [audioUrl]);

  useEffect(() => {
    let alive = true;
    api
      .villages()
      .then((vs) => {
        if (!alive) return;
        const slim = vs.map(({ id, name, name_hi, level }) => ({ id, name, name_hi, level }));
        setVillages(slim);
        writeLS('pukaar.villages', JSON.stringify(slim));
      })
      .catch(() => {
        /* offline: keep the cached list */
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (writing) textRef.current?.focus();
  }, [writing]);

  // A queued report that later flushes still gets its tracking code into "my reports".
  useEffect(() => {
    if (online) void flushQueue().then((r) => r.sent && setMine(myTrackCodes()));
  }, [online]);

  const village = villages.find((v) => v.id === villageId);
  const level: Level | undefined = village?.level;
  const hasContent = Boolean(rec.audioBlob || photo || text.trim());
  const canSend = Boolean(villageId) && hasContent && !rec.isRecording && phase.k === 'compose';

  function pickVillage(id: string) {
    setVillageId(id);
    writeLS('pukaar.myVillage', id);
  }

  function locate() {
    if (!navigator.geolocation) {
      setGpsState('fail');
      return;
    }
    setGpsState('busy');
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setGps({ lat: +p.coords.latitude.toFixed(5), lon: +p.coords.longitude.toFixed(5), acc: Math.round(p.coords.accuracy) });
        setGpsState('idle');
      },
      () => setGpsState('fail'),
      { enableHighAccuracy: true, timeout: 12000, maximumAge: 60000 },
    );
  }

  async function onPhoto(file: File | undefined) {
    if (!file) return;
    setPhotoBusy(true);
    try {
      setPhoto(await compressPhoto(file));
    } catch {
      setPhoto(file);
    } finally {
      setPhotoBusy(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  }

  async function queue() {
    await saveReportOffline({
      village_id: villageId,
      text: text.trim() || undefined,
      lat: gps?.lat ?? null,
      lon: gps?.lon ?? null,
      audio: toPendingAttachment(rec.audioBlob, 'voice.webm'),
      photo: toPendingAttachment(photo, 'photo.jpg'),
    });
    await refreshQueueCount();
    setPhase({ k: 'queued' });
  }

  async function send() {
    setErr(null);
    if (!villageId) {
      setErr(t('report.need.village'));
      return;
    }
    if (!hasContent) {
      setErr(t('report.need.content'));
      return;
    }
    setPhase({ k: 'sending' });
    if (!navigator.onLine) {
      await queue();
      return;
    }
    try {
      const res = await api.createReport({
        village_id: villageId,
        text: text.trim() || undefined,
        audio: rec.audioBlob,
        photo,
        lat: gps?.lat,
        lon: gps?.lon,
      });
      rememberTrackCode(res.track_code);
      setMine(myTrackCodes());
      setPhase({ k: 'done', code: res.track_code });
    } catch (e) {
      const ae = e instanceof ApiError ? e : new ApiError(0, null);
      if (ae.isNetwork || ae.status >= 500 || ae.status === 408 || ae.status === 429) {
        await queue();
      } else {
        setErr(t('report.error', { m: (lang === 'hi' && ae.messageHi) || ae.messageEn }));
        setPhase({ k: 'compose' });
      }
    }
  }

  function resetAll() {
    rec.reset();
    setPhoto(null);
    setText('');
    setWriting(false);
    setErr(null);
    setCopied(false);
    setPhase({ k: 'compose' });
  }

  const trackUrl = phase.k === 'done' ? `${window.location.origin}/t/${phase.code}` : '';

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(trackUrl);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  }

  const fab = <Call112 variant="fab" breathe={level === 'warning' || level === 'critical'} />;

  if (phase.k === 'done' || phase.k === 'queued') {
    const done = phase.k === 'done';
    return (
      <div className="report wrap-narrow">
        <section className={`result-card ${done ? 'is-done' : 'is-queued'}`} aria-live="polite">
          <span className="result-icon" aria-hidden="true">
            {done ? <CircleCheck /> : <Hourglass />}
            <i />
          </span>
          <h1 className="result-title">{done ? t('report.done.title') : t('report.queued.title')}</h1>
          {done ? (
            <>
              <p className="result-body">{t('report.done.body')}</p>
              <p className="code-label">{t('report.done.code')}</p>
              <p className="track-code" aria-label={phase.code.split('').join(' ')}>
                {phase.code}
              </p>
              <Link className="track-link" to={`/t/${phase.code}`}>
                {trackUrl.replace(/^https?:\/\//, '')}
              </Link>
              <div className="result-actions">
                <button type="button" className="btn btn-lg btn-accent btn-press" onClick={copyLink}>
                  {copied ? <Check aria-hidden="true" /> : <Copy aria-hidden="true" />} {copied ? t('common.copied') : t('common.copy')}
                </button>
                {'share' in navigator && (
                  <button
                    type="button"
                    className="btn btn-lg btn-ghost btn-press"
                    onClick={() => navigator.share({ title: 'Pukaar', url: trackUrl }).catch(() => {})}
                  >
                    <Share2 aria-hidden="true" /> {t('common.share')}
                  </button>
                )}
              </div>
            </>
          ) : (
            <p className="result-body">{t('report.queued.body')}</p>
          )}
          <button type="button" className="btn btn-lg btn-ghost btn-press" onClick={resetAll}>
            {t('report.another')}
          </button>
        </section>
        {fab}
      </div>
    );
  }

  const secs = Math.min(MAX_MS, rec.elapsedMs) / 1000;

  return (
    <div className="report wrap-narrow">
      <header className="report-head">
        <h1 className="report-title">{t('report.title')}</h1>
        <p className="report-lead">{t('report.lead')}</p>
      </header>

      <div className="report-where">
        <label className="field">
          <span className="field-label">{t('report.village')}</span>
          <span className="select-wrap">
            <select value={villageId} onChange={(e) => pickVillage(e.target.value)} className="select-xl">
              <option value="">{t('report.village.pick')}</option>
              {villages.map((v) => (
                <option key={v.id} value={v.id}>
                  {lang === 'hi' ? `${v.name_hi} (${v.name})` : `${v.name} (${v.name_hi})`}
                </option>
              ))}
            </select>
          </span>
        </label>
        {villages.length === 0 && <p className="small warn-text">{t('report.village.none')}</p>}
        {level && level !== 'normal' && (
          <div className="village-level-note">
            <LevelBadge level={level} size="sm" />
          </div>
        )}
        <button type="button" className={`btn btn-gps btn-press${gps ? ' is-set' : ''}`} onClick={locate} disabled={gpsState === 'busy'}>
          {gpsState === 'busy' ? <LoaderCircle className="spin" aria-hidden="true" /> : <MapPin aria-hidden="true" />}
          {gpsState === 'busy' ? t('report.gps.busy') : gps ? t('report.gps.ok', { m: gps.acc }) : t('report.gps')}
        </button>
        {gpsState === 'fail' && <p className="small warn-text">{t('report.gps.fail')}</p>}
      </div>

      {rec.isRecording ? (
        <section className="rec-panel" aria-live="polite">
          <p className="rec-state">
            <span className="rec-dot" aria-hidden="true" /> {t('report.recording')}
          </p>
          <div className="wave" aria-hidden="true">
            {rec.levels.map((v, i) => (
              <i key={i} style={{ transform: `scaleY(${0.08 + v * 0.92})` }} />
            ))}
          </div>
          <p className="rec-timer">
            <span>{secs.toFixed(0).padStart(2, '0')}</span> / 20 <span className="small">{lang === 'hi' ? 'सेकंड' : 's'}</span>
          </p>
          <div className="rec-progress" aria-hidden="true">
            <i style={{ transform: `scaleX(${secs / 20})` }} />
          </div>
          <button type="button" className="btn btn-stop btn-press" onClick={rec.stop} aria-label={t('report.stop.aria')}>
            <Square aria-hidden="true" /> {t('report.stop')}
          </button>
        </section>
      ) : (
        <div className="big-actions" role="group" aria-label={t('report.lead')}>
          <button type="button" className={`big-btn big-speak btn-press${rec.audioBlob ? ' is-done' : ''}`} onClick={() => void rec.start()} aria-label={t('report.speak.aria')}>
            <span className="bb-icon" aria-hidden="true">
              <Mic />
            </span>
            <span className="bb-word">{t('report.speak')}</span>
            <span className="bb-hint">{t('report.seconds', { s: 20 })}</span>
            {rec.audioBlob && <Check className="bb-check" aria-hidden="true" />}
          </button>
          <button type="button" className={`big-btn big-photo btn-press${photo ? ' is-done' : ''}`} onClick={() => fileRef.current?.click()} disabled={photoBusy}>
            <span className="bb-icon" aria-hidden="true">
              {photoBusy ? <LoaderCircle className="spin" /> : <Camera />}
            </span>
            <span className="bb-word">{t('report.photo')}</span>
            {photo && <Check className="bb-check" aria-hidden="true" />}
          </button>
          <button
            type="button"
            className={`big-btn big-write btn-press${text.trim() ? ' is-done' : ''}`}
            onClick={() => setWriting(true)}
            aria-expanded={writing}
            aria-controls="report-text"
          >
            <span className="bb-icon" aria-hidden="true">
              <PenLine />
            </span>
            <span className="bb-word">{t('report.write')}</span>
            {text.trim() && <Check className="bb-check" aria-hidden="true" />}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="sr-only"
            tabIndex={-1}
            aria-hidden="true"
            onChange={(e) => void onPhoto(e.target.files?.[0])}
          />
        </div>
      )}

      {rec.error && (
        <p className="warn-text" role="alert">
          {rec.error === 'denied' ? t('report.mic.denied') : t('report.mic.unsupported')}
        </p>
      )}
      {photoBusy && <p className="small muted">{t('report.photo.busy')}</p>}

      <div className="attachments">
        {audioUrl && (
          <div className="attach">
            <Mic aria-hidden="true" className="attach-icon" />
            <span className="attach-label">{t('report.voice.ready')}</span>
            <audio src={audioUrl} controls preload="metadata" aria-label={t('report.voice.play')} />
            <button type="button" className="icon-btn" onClick={rec.reset} aria-label={t('report.voice.remove')}>
              <Trash2 aria-hidden="true" />
            </button>
          </div>
        )}
        {photoUrl && (
          <div className="attach attach-photo">
            <img src={photoUrl} alt={t('report.photo.ready')} />
            <span className="attach-label">
              {t('report.photo.ready')} · {Math.round((photo?.size ?? 0) / 1024)} KB
            </span>
            <button type="button" className="icon-btn" onClick={() => setPhoto(null)} aria-label={t('report.photo.remove')}>
              <X aria-hidden="true" />
            </button>
          </div>
        )}
        {writing && (
          <label className="field" htmlFor="report-text">
            <span className="field-label">{t('report.text.label')}</span>
            <textarea
              id="report-text"
              ref={textRef}
              value={text}
              onChange={(e) => setText(e.target.value.slice(0, 500))}
              rows={3}
              placeholder={t('report.text.placeholder')}
              className="textarea-xl"
            />
            <span className="small muted counter-chars">{text.length}/500</span>
          </label>
        )}
      </div>

      {err && (
        <p className="error-text" role="alert">
          {err}
        </p>
      )}

      <div className="send-bar">
        <button type="button" className="btn btn-send btn-press" onClick={() => void send()} disabled={!canSend} aria-describedby="send-note">
          {phase.k === 'sending' ? <LoaderCircle className="spin" aria-hidden="true" /> : <Send aria-hidden="true" />}
          {phase.k === 'sending' ? t('report.sending') : t('report.send')}
          {!online && <span className="send-offline">· {t('shell.offline')}</span>}
        </button>
        <p id="send-note" className="send-note">
          {!villageId ? t('report.need.village') : !hasContent ? t('report.need.content') : t('report.safety')}
        </p>
      </div>

      {mine.length > 0 && (
        <section className="my-reports" aria-labelledby="mine-h">
          <h2 id="mine-h" className="h-sec">
            {t('report.mine')}
          </h2>
          <ul>
            {mine.slice(0, 5).map((m) => (
              <li key={m.code}>
                <Link to={`/t/${m.code}`} className="mine-row">
                  <span className="mine-code">{m.code}</span>
                  <span className="small muted">{fmtAgo(new Date(m.at).toISOString(), lang)}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
      {fab}
    </div>
  );
}
