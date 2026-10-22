import { BellRing } from 'lucide-react';
import { useT } from '../i18n';
import { fmtDate } from '../lib/format';
import { lastTestedLine, type VillageSirens } from '../lib/sirens';
import '../sirens.css';

/** The public village page's one siren line: "Siren last tested <date>: passed" (red when failed or overdue). */
export function SirenLastTested({ sirens }: { sirens?: VillageSirens | null }) {
  const { lang } = useT();
  const line = lastTestedLine(sirens, lang, fmtDate);
  if (!line) return null;
  return (
    <p className={`siren-tested small ${line.tone === 'bad' ? 'bad-text' : 'ok-text'}`} role="note">
      <BellRing aria-hidden="true" /> {line.text}
    </p>
  );
}
