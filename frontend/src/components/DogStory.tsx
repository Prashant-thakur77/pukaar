import { ArrowUpRight } from 'lucide-react';
import { useT } from '../i18n';
import { Reveal } from './Reveal';

/** Sourced story: The Tribune, 9 July 2025 (checked 2026-10-22). The quote is the villager's own words. */
const DOG = {
  source: 'The Tribune, 9 Jul 2025',
  url: 'https://www.tribuneindia.com/news/himachal/pet-dog-emerges-saviour-in-mandi-village-saves-60-lives-amid-monsoon-fury',
};
/** The IMD red alert for Mandi on 30 June 2025 (ANI, via Business Standard). */
const RED_ALERT = {
  source: 'Business Standard, 30 Jun 2025',
  url: 'https://www.business-standard.com/india-news/red-alert-issued-in-mandi-beas-river-flooded-after-heavy-rainfall-125063000167_1.html',
};

function Quote() {
  const { lang } = useT();
  return (
    <blockquote className="dog-quote">
      <p lang="en">“Can we trust a dog to warn us next time?”</p>
      <footer>{lang === 'hi' ? 'मोहन, सियाठी गाँव, मंडी' : 'Mohan, Siyathi village, Mandi'}</footer>
    </blockquote>
  );
}

/**
 * The night of 30 June 2025 in Siyathi: a red alert was out for the district, and what woke the
 * village was a dog. Told plainly, with its sources; `quote` is the short form for other pages.
 */
export function DogStory({ variant = 'full' }: { variant?: 'full' | 'quote' }) {
  const { lang } = useT();
  if (variant === 'quote')
    return (
      <section className="band story-dog is-quote" aria-label={lang === 'hi' ? 'सियाठी की रात' : 'The night in Siyathi'}>
        <div className="wrap dog-quote-wrap">
          <Quote />
          <p className="dog-answer">
            {lang === 'hi'
              ? '30 जून 2025 की रात सियाठी के 60 से ज़्यादा लोगों को एक कुत्ते के भौंकने से समय पर निकलने का मौका मिला। यह पन्ना जाँचता है कि पुकार कितनी पहले चेतावनी देता।'
              : 'On the night of 30 June 2025 a dog’s barking got more than 60 people in Siyathi out in time. This page checks how much earlier Pukaar would have warned.'}{' '}
            <a className="dog-src-link" href={DOG.url} target="_blank" rel="noreferrer">
              {DOG.source} <ArrowUpRight aria-hidden="true" />
            </a>
          </p>
        </div>
      </section>
    );
  return (
    <section className="band story-dog" aria-labelledby="dog-title">
      <div className="wrap dog-grid">
        <Reveal variant="slide">
          <p className="eyebrow">{lang === 'hi' ? 'उसी रात · सियाठी, मंडी' : 'That same night · Siyathi, Mandi'}</p>
          <h2 id="dog-title" className="display-3">
            {lang === 'hi' ? 'गाँव को एक कुत्ते ने जगाया।' : 'A dog woke the village.'}
          </h2>
        </Reveal>
        <Reveal delay={100} className="dog-body">
          <p className="dog-text" lang={lang}>
            {lang === 'hi'
              ? 'उस दिन मंडी ज़िले के लिए रेड अलर्ट जारी था। आधी रात के ठीक बाद सियाठी गाँव में एक पालतू कुत्ता भौंकने लगा। उसकी आवाज़ पर 20 घरों के 60 से ज़्यादा लोग पाँच मिनट में बाहर निकल आए।'
              : 'A red alert was out for Mandi district that day. Just past midnight in Siyathi village, a pet dog began to bark. Within five minutes more than 60 people from 20 households were out of their homes.'}
          </p>
          <Quote />
          <p className="dog-answer">
            {lang === 'hi' ? 'पुकार इसी सवाल का जवाब बनना चाहता है: ऐसी चेतावनी जो किस्मत पर न टिकी हो।' : 'Pukaar is our answer to that question: a warning that does not rest on luck.'}
          </p>
          <p className="fact-src dog-src">
            {lang === 'hi' ? 'स्रोत' : 'Sources'}:{' '}
            <a href={DOG.url} target="_blank" rel="noreferrer">
              {DOG.source} <ArrowUpRight aria-hidden="true" />
            </a>
            {' · '}
            <a href={RED_ALERT.url} target="_blank" rel="noreferrer">
              {RED_ALERT.source} <ArrowUpRight aria-hidden="true" />
            </a>
          </p>
        </Reveal>
      </div>
    </section>
  );
}
