import { ArrowDown } from 'lucide-react';
import { useT } from '../i18n';
import { LevelIcon } from './Level';
import { Call112 } from './Shell';
import { LEVELS, type Level } from '../types';

type Line = { hi: string; en: string };

/** Plain actions for each level, the same advice the spoken alerts give. Hindi first. */
const DO: Record<Level, Line[]> = {
  normal: [
    { hi: 'अभी कुछ करने की ज़रूरत नहीं। पुकार हर 15 मिनट नदी और बारिश जाँचता है।', en: 'Nothing to do now. Pukaar checks the river and rain every 15 minutes.' },
    { hi: 'नीचे देख लें कि सबसे पास की ऊँची, सुरक्षित जगह कौन-सी है।', en: 'Look below for your nearest high, safe place.' },
  ],
  watch: [
    { hi: 'नदी और नालों के किनारे न जाएँ।', en: 'Keep away from the river and streams.' },
    { hi: 'काग़ज़, दवा, टॉर्च और पानी एक थैले में रख लें। फ़ोन चार्ज रखें।', en: 'Put papers, medicine, a torch and water in one bag. Keep your phone charged.' },
  ],
  warning: [
    { hi: 'जाने के लिए तैयार रहें: नीचे दी गई ऊँची जगह और रास्ता अभी देख लें।', en: 'Be ready to leave: look at the high place and the route below now.' },
    { hi: 'बुज़ुर्ग, बच्चे, बीमार और पशु पहले ले जाने की तैयारी करें।', en: 'Plan to move the elderly, children, the sick and animals first.' },
    { hi: 'नदी, नाले, पुल और ढलानों से दूर रहें।', en: 'Stay away from the river, streams, bridges and slopes.' },
  ],
  critical: [
    { hi: 'अभी ऊँची, सुरक्षित जगह पर जाएँ। सामान के लिए न रुकें।', en: 'Go to high, safe ground now. Do not stop for belongings.' },
    { hi: 'पुल या बहता पानी पार न करें।', en: 'Do not cross bridges or moving water.' },
    { hi: 'जान को ख़तरा हो तो 112 पर कॉल करें।', en: 'If a life is in danger, call 112.' },
  ],
};

/** When the forecast data is missing, Normal is not a promise: watch for yourself. */
const NO_DATA: Line[] = [
  { hi: 'पूर्वानुमान डेटा अभी नहीं मिल रहा, इसलिए “सामान्य” पर भरोसा न करें।', en: 'Forecast data is not coming in, so do not rely on “Normal”.' },
  { hi: 'नदी और नालों पर ख़ुद नज़र रखें; किनारे न जाएँ।', en: 'Watch the river and streams yourself; stay off the banks.' },
  { hi: 'पानी तेज़ी से बढ़े या ख़तरा दिखे, तो ऊँची जगह जाएँ और 112 पर कॉल करें।', en: 'If the water rises fast or you see danger, go to high ground and call 112.' },
];

/** What each step of the scale asks of you, in two words. */
const MEANS: Record<Level, Line> = {
  normal: { hi: 'सब सामान्य', en: 'All normal' },
  watch: { hi: 'नज़र रखें', en: 'Stay alert' },
  warning: { hi: 'तैयार रहें', en: 'Get ready' },
  critical: { hi: 'अभी निकलें', en: 'Leave now' },
};

/**
 * "What to do now" for the village's level, and the four-step scale with this village marked, so
 * anyone can read the level and the action in a few seconds (after the Environment Agency's
 * "Check for flooding" pages).
 */
export function WhatToDo({ level, whereId, unknown = false }: { level: Level; whereId?: string; unknown?: boolean }) {
  const { t, lang } = useT();
  // `unknown`: the level reads Normal only because no data says otherwise.
  const lines = unknown ? NO_DATA : DO[level];
  const urgent = unknown || level === 'warning' || level === 'critical';
  return (
    <section className={`v-do lv-${unknown ? 'nodata' : level}`} aria-labelledby="vdo-h">
      <h2 id="vdo-h" className="v-do-h">
        {t('village.do')}
      </h2>
      <ol className="v-do-list">
        {lines.map((l) => (
          <li key={l.en}>
            <span lang="hi">{l.hi}</span>
            {lang === 'en' && <span className="v-do-en">{l.en}</span>}
          </li>
        ))}
      </ol>
      <div className="v-do-actions">
        {whereId && (
          <a href={`#${whereId}`} className={`btn ${urgent ? 'btn-accent' : 'btn-night'} btn-press`}>
            <ArrowDown aria-hidden="true" /> {t('village.do.where')}
          </a>
        )}
        {urgent && <Call112 />}
      </div>
      <ol className="v-scale" aria-label={t('village.scale')}>
        {LEVELS.map((l) => (
          <li key={l} className={`lv-${l}${l === level && !unknown ? ' is-now' : ''}`} aria-current={l === level && !unknown ? 'step' : undefined}>
            <span className="vs-word">
              <LevelIcon level={l} className="vs-icon" />
              {t(`level.${l}`)}
            </span>
            <span className="vs-means">{MEANS[l][lang]}</span>
            {l === level && !unknown && <span className="vs-now">{t('village.scale.now')}</span>}
          </li>
        ))}
      </ol>
    </section>
  );
}
