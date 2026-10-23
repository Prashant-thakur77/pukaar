import { levelWord, useT } from '../i18n';
import { fmtNumber } from '../lib/format';
import { STORY_BANDS, STORY_DOMAIN, STORY_RAIN } from '../lib/story';
import { RiverLine } from './RiverLine';

/**
 * Gohar's 24-hour rain forecast through 7-11 July 2023 against IMD's three bands (S1 drawing the S3 story). The
 * marker sits at `cursor`; what came after it is dimmed. The home page shows one still frame of it.
 */
export default function StoryChart({ cursor, height = 260, label }: { cursor: number; height?: number; label?: string }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const when = new Intl.DateTimeFormat(hi ? 'hi-IN' : 'en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(cursor);
  const lines = (['watch', 'warning', 'critical'] as const).map((l) => ({ level: l, value: STORY_BANDS[l], word: `${levelWord(l, lang)} ${fmtNumber(STORY_BANDS[l], lang, 1)}` }));
  return (
    <RiverLine
      observed={STORY_RAIN}
      lines={lines}
      domain={STORY_DOMAIN}
      cursor={cursor}
      veil
      height={height}
      nowLabel={`${when} IST`}
      label={
        label ??
        (hi
          ? `गोहर, 7 से 11 जुलाई 2023: अगले 24 घंटे की बारिश का अनुमान, मिमी में; IMD सीमाएँ ${STORY_BANDS.watch}, ${STORY_BANDS.warning} और ${STORY_BANDS.critical} मिमी`
          : `Gohar, 7 to 11 July 2023: the 24-hour rain forecast in mm; IMD bands ${STORY_BANDS.watch}, ${STORY_BANDS.warning} and ${STORY_BANDS.critical} mm`)
      }
    />
  );
}
