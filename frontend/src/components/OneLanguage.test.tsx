import { afterEach, describe, expect, it } from 'vitest';
import { act } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';
import { ActionList, LevelBanner, StickyActionBar, VillageRows } from './Answer';
import { LevelBadge, LevelLegend } from './Level';
import { DataBadge } from './DataStatus';
import { PilotNotice } from './PilotNotice';
import { QuotedAlert } from './QuotedAlert';
import { Call112, Wordmark } from './Shell';
import { usePrefs, type Lang } from '../store';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** Every page shows one language: no Devanagari on an English page, no English words on a Hindi page. */
const DEVANAGARI = /[ऀ-ॿ]/;
const ENGLISH_WORD = /\b(?!(?:SMS|IMD|DDMA)\b)[A-Za-z]{3,}\b/;

let root: Root | null = null;
let host: HTMLDivElement | null = null;
afterEach(() => {
  act(() => root?.unmount());
  host?.remove();
  root = null;
});

function renderIn(lang: Lang) {
  act(() => usePrefs.setState({ lang }));
  host = document.createElement('div');
  document.body.append(host);
  root = createRoot(host);
  const means = { hi: 'तैयार रहें', en: 'Get ready' };
  const lines = [
    { hi: 'नदी और नालों के किनारे न जाएँ।', en: 'Keep away from the river and streams.' },
    { hi: 'ऊँची जगह और वहाँ तक का रास्ता अभी देख लें।', en: 'Look at the high place and the route to it now.' },
  ];
  act(() =>
    root!.render(
      <MemoryRouter>
        <Wordmark />
        <Call112 />
        <LevelBanner level="warning" means={means} title="—" />
        <LevelBanner level="normal" unknown means={means} title="—" />
        <ActionList lines={lines} level="warning" />
        <StickyActionBar level="critical" place={null} />
        <VillageRows
          label="—"
          villages={[
            { id: 'gohar', name: 'Gohar', name_hi: 'गोहर', level: 'warning' },
            { id: 'pandoh', name: 'Pandoh', name_hi: 'पंडोह', level: 'normal', unknown: true },
          ]}
        />
        <LevelBadge level="critical" />
        <LevelLegend />
        <DataBadge kind="stale" />
        <PilotNotice />
      </MemoryRouter>,
    ),
  );
  const labels = [...host.querySelectorAll('[aria-label]')].map((e) => e.getAttribute('aria-label')).join(' ');
  return `${host.textContent} ${labels}`;
}

describe('one language per page', () => {
  it('an English page has no Devanagari: village names, level words, 112 and the brand in English', () => {
    const text = renderIn('en');
    expect(text).not.toMatch(DEVANAGARI);
    expect(text).toContain('Gohar');
    expect(text).toContain('Warning');
    expect(text).toContain('Pukaar');
    expect(text).toContain('Emergency');
  });

  it('a Hindi page has no English words: names, level words and the brand in Devanagari', () => {
    const text = renderIn('hi');
    expect(text).not.toMatch(ENGLISH_WORD);
    expect(text).toContain('गोहर');
    expect(text).toContain('चेतावनी');
    expect(text).toContain('पुकार');
  });

  it('keeps an alert\'s spoken Hindi on an English page only as a marked quote, with its English meaning', () => {
    act(() => usePrefs.setState({ lang: 'en' }));
    host = document.createElement('div');
    document.body.append(host);
    root = createRoot(host);
    act(() => root!.render(<QuotedAlert hi="गोहर: नदी किनारे न जाएँ।" en="Gohar: do not go near the riverbank." />));
    const quote = host.querySelector('[data-quoted-sample] blockquote');
    expect(quote?.getAttribute('lang')).toBe('hi');
    expect(host.textContent).toContain('In English: Gohar: do not go near the riverbank.');
    act(() => usePrefs.setState({ lang: 'hi' }));
    expect(host.querySelector('[data-quoted-sample]')).toBeNull();
    expect(host.textContent).not.toMatch(ENGLISH_WORD);
  });
});
