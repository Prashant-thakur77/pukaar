import { Info } from 'lucide-react';
import { useT } from '../i18n';
import './notice.css';

/**
 * The standing notice on the home and village pages: Pukaar is a pilot, not the official warning. Calm and
 * small on purpose (never a level colour, never a banner): the official warnings and the emergency numbers come
 * first. In the page's language.
 */
export function PilotNotice() {
  const { lang } = useT();
  return (
    <p className="pilot-note" role="note">
      <Info aria-hidden="true" />
      <span>
        {lang === 'hi' ? 'पायलट प्रणाली; DDMA/IMD की चेतावनी मानें; आपात स्थिति में 112 / 1077' : 'Pilot system; follow DDMA and IMD warnings; emergency 112 / 1077'}
      </span>
    </p>
  );
}
