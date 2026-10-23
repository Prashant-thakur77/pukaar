import { useState } from 'react';
import { Copy, Download, Mail, RadioTower } from 'lucide-react';
import { ApiError } from '../api';
import { useT } from '../i18n';
import { canRequestSachet, reachApi, sachetClipboard, saveFile, type SachetPackage, type SachetVia } from '../lib/reach';
import type { Alert } from '../types';
import { DeniedNote, ErrorState } from './States';
import '../styles/reach.css';

/*
 * "Request SACHET / cell broadcast" (backend services/sachet_request.py). Only HPSDMA can issue on SACHET or cell
 * broadcast; this prepares the request: a CAP 1.2 file with the village polygon, Hindi and English text within
 * cell-broadcast limits, and the steps. The officer downloads, copies or e-mails it; each is in the audit trail.
 * Nothing here says a broadcast went out, because Pukaar cannot know.
 */

const RADII = [3, 5, 10];

export function SachetRequest({ alert }: { alert: Alert }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const [pkg, setPkg] = useState<SachetPackage | null>(null);
  const [radius, setRadius] = useState(5);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [note, setNote] = useState('');
  if (!canRequestSachet(alert)) return null;

  const get = async (via: SachetVia, r = radius) => {
    setBusy(true);
    setErr(null);
    try {
      const p = await reachApi.sachet(alert.id, via, r);
      setPkg(p);
      return p;
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
      return null;
    } finally {
      setBusy(false);
    }
  };
  const download = async () => {
    const p = await get('download');
    if (p) {
      saveFile(p.filename, p.cap_xml);
      setNote(hi ? `${p.filename} सहेजी गई।` : `${p.filename} saved.`);
    }
  };
  const copy = async () => {
    const p = await get('copy');
    if (!p) return;
    try {
      await navigator.clipboard.writeText(sachetClipboard(p));
      setNote(hi ? 'संदेश और चरण कॉपी हो गए।' : 'Texts and steps copied.');
    } catch {
      setNote(hi ? 'कॉपी नहीं हो सका: नीचे से चुनकर कॉपी करें।' : 'Could not copy: select the text below instead.');
    }
  };
  const email = async () => {
    const p = await get('email');
    if (p) window.location.href = p.mailto;
  };

  return (
    <section className="sachet" aria-labelledby={`sachet-${alert.id}`}>
      <h3 id={`sachet-${alert.id}`} className="dp-sec-h">
        <RadioTower aria-hidden="true" /> {hi ? 'SACHET / सेल ब्रॉडकास्ट का अनुरोध' : 'Request SACHET / cell broadcast'}
      </h3>
      <p className="sachet-meta">
        {hi
          ? 'केवल HPSDMA इसे जारी कर सकता है। पुकार अनुरोध तैयार करता है; भेजता नहीं।'
          : 'Only HPSDMA can issue it. Pukaar prepares the request; it does not send it.'}
      </p>
      {!pkg ? (
        <div className="sachet-actions">
          <button type="button" className="btn btn-accent" disabled={busy} onClick={() => void get('view')}>
            <RadioTower aria-hidden="true" /> {hi ? 'अनुरोध तैयार करें' : 'Prepare the request'}
          </button>
        </div>
      ) : (
        <>
          {pkg.exercise && (
            <p className="dp-note is-warn">{hi ? 'अभ्यास: इसे जनता के लिए कभी जारी न करें।' : 'Exercise: never issue this to the public.'}</p>
          )}
          <label className="field">
            <span className="field-label">{hi ? 'क्षेत्र (गाँव के चारों ओर)' : 'Area (around the village)'}</span>
            <select
              value={radius}
              disabled={busy}
              onChange={(e) => {
                const r = Number(e.target.value);
                setRadius(r);
                void get('view', r);
              }}
            >
              {RADII.map((r) => (
                <option key={r} value={r}>
                  {r} km
                </option>
              ))}
            </select>
          </label>
          <p className="field-label">{hi ? 'हिंदी (सेल ब्रॉडकास्ट)' : 'Hindi (cell broadcast)'}</p>
          <p className="sachet-text" lang="hi">
            {pkg.text_hi}
          </p>
          <p className="sachet-meta">
            {pkg.limits.hi.chars} / {pkg.limits.hi.max_chars} {hi ? 'अक्षर' : 'characters'}, {pkg.limits.hi.pages}{' '}
            {hi ? 'पेज' : pkg.limits.hi.pages === 1 ? 'page' : 'pages'} ({pkg.limits.hi.encoding})
          </p>
          <p className="field-label">{hi ? 'अंग्रेज़ी (सेल ब्रॉडकास्ट)' : 'English (cell broadcast)'}</p>
          <p className="sachet-text" lang="en">
            {pkg.text_en}
          </p>
          <p className="sachet-meta">
            {pkg.limits.en.chars} / {pkg.limits.en.max_chars} {hi ? 'अक्षर' : 'characters'}, {pkg.limits.en.pages}{' '}
            {hi ? 'पेज' : pkg.limits.en.pages === 1 ? 'page' : 'pages'} ({pkg.limits.en.encoding})
          </p>
          <ol className="sachet-steps">
            {(hi ? pkg.steps_hi : pkg.steps_en).map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ol>
          <div className="sachet-actions">
            <button type="button" className="btn btn-accent" disabled={busy} onClick={() => void download()}>
              <Download aria-hidden="true" /> {hi ? 'CAP फ़ाइल डाउनलोड' : 'Download the CAP file'}
            </button>
            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void copy()}>
              <Copy aria-hidden="true" /> {hi ? 'संदेश कॉपी करें' : 'Copy the texts'}
            </button>
            <button type="button" className="btn btn-ghost" disabled={busy} onClick={() => void email()}>
              <Mail aria-hidden="true" /> {hi ? 'ई-मेल करें' : 'E-mail it'}
            </button>
          </div>
          <p className="sachet-meta">{hi ? pkg.not_sent_hi : pkg.not_sent_en}</p>
        </>
      )}
      {note && (
        <p className="sachet-meta" role="status">
          {note}
        </p>
      )}
      {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
    </section>
  );
}
