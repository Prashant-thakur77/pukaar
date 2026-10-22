import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, ChevronRight, CircleCheck, Eye, Map as MapIcon, Mic, PhoneCall, UserCheck } from 'lucide-react';
import { api } from '../api';
import { Freshness, LevelBanner, VillageRows, type RowVillage } from '../components/Answer';
import { usePoll } from '../hooks/usePoll';
import { useHandOff } from '../boot/handoff';
import { useT } from '../i18n';
import { LEAD, MEANS } from '../lib/actions';
import { levelIsKnown } from '../lib/dataStatus';
import { levelRank } from '../lib/levels';
import { DEFAULT_COST_INPUTS, estimatePilotCost, fmtRupees } from '../lib/pilotCost';
import { readLS, writeLS } from '../store';
import type { PublicOverview } from '../types';
import { ValleySketch } from '../components/ValleySketch';
// The alert lead from the story data (scripts/story.py), never typed by hand.
import { lead_hours_watch_to_peak_day as GOHAR_ALERT_LEAD_H } from '../data/story-gohar-2023.json';
import './landing.css';

const CACHE_KEY = 'pukaar.overview';

/** The last overview this phone saw, so the status paints at once on the next visit and with no signal. */
function readCached(): PublicOverview | null {
  const raw = readLS(CACHE_KEY);
  if (!raw) return null;
  try {
    const v = JSON.parse(raw) as PublicOverview;
    return Array.isArray(v?.villages) ? v : null;
  } catch {
    return null;
  }
}

const PER_VILLAGE_SEASON = fmtRupees(estimatePilotCost(DEFAULT_COST_INPUTS).perSeason);

/**
 * गाँवों का हाल: the status of the five villages first (is anyone in danger right now, and where do I tap),
 * then, below the fold, what Pukaar is, in four short screens for a jury or a district.
 */
export default function Landing() {
  const { t, lang } = useT();
  const hi = lang === 'hi';
  const [cached] = useState(readCached);
  const { data: fresh, error } = usePoll(() => api.overview(), [], 30000);
  useEffect(() => {
    if (fresh) writeLS(CACHE_KEY, JSON.stringify(fresh));
  }, [fresh]);
  const data = fresh ?? cached;
  // The boot painter drew this status already: hand over once there is something to show.
  useHandOff(Boolean(data) || Boolean(error));
  const offline = !fresh && Boolean(cached) && Boolean(error?.isNetwork);

  const villages = data?.villages ?? [];
  const rows: RowVillage[] = villages.map((v) => ({ id: v.id, name: v.name, name_hi: v.name_hi, level: v.level, unknown: !levelIsKnown(v) }));
  const raised = [...villages].filter((v) => levelRank(v.level) >= levelRank('watch')).sort((a, b) => levelRank(b.level) - levelRank(a.level));
  const unknown = villages.filter((v) => !levelIsKnown(v));
  const checkedAt = villages.reduce<string | null>((m, v) => (v.data_ok_at && (!m || v.data_ok_at > m) ? v.data_ok_at : m), null);
  const n = villages.length;

  return (
    <div className="home">
      <section className="home-status wrap" aria-labelledby="home-h" data-tour="hero">
        <div className="home-now">
          <p className="home-region">{hi ? 'हिमाचल · मंडी और हमीरपुर' : 'Himachal · Mandi and Hamirpur'}</p>
          {!data ? (
            <>
              <h1 id="home-h" className="home-h1">
                {t('nav.status')}
              </h1>
              <p className="home-wait">{hi ? 'हर गाँव का हाल आ रहा है…' : 'Getting each village’s level…'}</p>
            </>
          ) : raised.length === 0 ? (
            <>
              <h1 id="home-h" className="home-h1">
                {unknown.length > 0 ? (
                  hi ? (
                    <>{unknown.length} गाँव का डेटा नहीं मिल रहा</>
                  ) : (
                    <>No data for {unknown.length} {unknown.length === 1 ? 'village' : 'villages'}</>
                  )
                ) : hi ? (
                  <>
                    आज सब {n} गाँव{' '}
                    <span className="home-ok">
                      <CircleCheck aria-hidden="true" />
                      सामान्य
                    </span>{' '}
                    हैं।
                  </>
                ) : (
                  <>
                    All {n} villages are at{' '}
                    <span className="home-ok">
                      <CircleCheck aria-hidden="true" />
                      Normal
                    </span>
                    .
                  </>
                )}
              </h1>
              {unknown.length > 0 && <p className="home-lead">{hi ? '‘सामान्य’ पर भरोसा न करें; नदी पर ख़ुद नज़र रखें।' : 'Do not rely on “Normal”; watch the river yourself.'}</p>}
              <Freshness at={checkedAt} offline={offline} next />
            </>
          ) : (
            <>
              <h1 id="home-h" className="sr-only">
                {t('nav.status')}
              </h1>
              <div className="home-banners">
                {raised.map((v) => (
                  <LevelBanner
                    key={v.id}
                    heading="h2"
                    level={v.level}
                    means={MEANS[v.level]}
                    title={
                      <Link to={`/village/${v.id}`} className="home-banner-link">
                        <span lang="hi">{v.name_hi}</span> <span className="lvb-en" lang="en">{v.name}</span>
                        <span className="home-banner-go">
                          {hi ? 'क्या करें' : 'What to do'} <ChevronRight aria-hidden="true" />
                        </span>
                      </Link>
                    }
                    why={<span lang="hi">{LEAD[v.level].hi}</span>}
                  />
                ))}
              </div>
              {raised.length < n && (
                <p className="home-lead">
                  {hi ? `बाक़ी ${n - raised.length} गाँव सामान्य हैं।` : `The other ${n - raised.length} villages are at Normal.`}
                </p>
              )}
              <Freshness at={checkedAt} offline={offline} next />
            </>
          )}
        </div>

        <div className="home-pick">
          <h2 className="home-h2">{hi ? 'अपना गाँव चुनें' : 'Choose your village'}</h2>
          {rows.length > 0 ? (
            <VillageRows villages={rows} label={hi ? 'पाँच गाँव' : 'The villages'} />
          ) : (
            /* The list's own height, held while it loads, so nothing below it jumps when it arrives. */
            <p className="vrows vrows-wait">{hi ? 'गाँवों की सूची आ रही है…' : 'Loading the villages…'}</p>
          )}
          <div className="home-acts">
            <Link to="/report" className="home-report">
              <Mic aria-hidden="true" />
              <span>
                <span lang="hi">पानी बढ़ रहा है? सूचना दें</span>
                {!hi && (
                  <span className="home-report-en" lang="en">
                    Water rising? Report it
                  </span>
                )}
              </span>
            </Link>
            <Link to="/live" className="go-link">
              <MapIcon aria-hidden="true" /> {t('nav.map')} <ChevronRight aria-hidden="true" />
            </Link>
          </div>
        </div>

        {/* The story begins here: the valley (the seam for the live S2 map) and the line. Beside the status on a
            desk, under it on a phone. */}
        <div className="home-lede">
          <ValleySketch villages={villages} />
          <h2 id="story-h" className="home-display" lang="hi">
            नदी से पहले, गाँव तक।
          </h2>
          <p className="home-para">
            {hi
              ? 'पुकार हर 15 मिनट बारिश और नदी का पूर्वानुमान पढ़ता है। ख़तरा दिखे तो एक अधिकारी चेतावनी मंज़ूर करता है, और गाँव के हर फ़ोन पर हिंदी में बोली गई चेतावनी पहुँचती है।'
              : 'Every 15 minutes Pukaar reads the rain and river forecasts. When danger shows, an officer approves the alert, and every phone in the village hears it spoken in Hindi.'}
          </p>
        </div>
      </section>

      <section className="home-band" aria-labelledby="how-h">
        <div className="wrap">
          <h2 id="how-h" className="home-h2">
            {hi ? 'यह कैसे काम करता है' : 'How it works'}
          </h2>
          <ol className="home-steps">
            <li>
              <Eye aria-hidden="true" />
              <h3 lang="hi">देखना</h3>
              <p>{hi ? 'हर 15 मिनट, हर गाँव की बारिश और नदी जाँची जाती है। स्तर कोड तय करता है, कोई अंदाज़ा नहीं।' : 'Every 15 minutes each village’s rain and river are checked. Fixed rules set the level, not a guess.'}</p>
            </li>
            <li>
              <UserCheck aria-hidden="true" />
              <h3 lang="hi">मंज़ूरी</h3>
              <p>{hi ? 'ड्यूटी पर एक अधिकारी चेतावनी पढ़कर एक टैप में मंज़ूर करता है। जवाब न मिले तो फ़ोन बजता है।' : 'The officer on duty reads the alert and approves it with one tap. No answer, and their phone rings.'}</p>
            </li>
            <li>
              <PhoneCall aria-hidden="true" />
              <h3 lang="hi">पुकार</h3>
              <p>{hi ? 'हर फ़ोन पर हिंदी में बोली गई कॉल और संदेश: क्या हुआ, और अभी क्या करें।' : 'A spoken Hindi call and message to every phone: what is happening, and what to do now.'}</p>
            </li>
          </ol>
          <Link to="/how" className="go-link">
            {hi ? 'पूरा तरीका' : 'The full method'} <ArrowRight aria-hidden="true" />
          </Link>
        </div>
      </section>

      <section className="home-band home-proof" aria-labelledby="proof-h">
        <div className="wrap home-split">
          <p className="home-num" aria-hidden="true">
            {GOHAR_ALERT_LEAD_H}
            <span>{hi ? 'घंटे' : 'h'}</span>
          </p>
          <div>
            <h2 id="proof-h" className="home-h2">
              {hi ? `${GOHAR_ALERT_LEAD_H} घंटे पहले चेतावनी मिल सकती थी` : `The warning could have come ${GOHAR_ALERT_LEAD_H} hours earlier`}
            </h2>
            <p className="home-para">
              {hi
                ? 'जुलाई 2023 की बाढ़ के असली पूर्वानुमान पर पुकार के नियम चलाए गए: गोहर में नदी के सबसे ऊँचे दिन से इतने घंटे पहले ‘सतर्क’ आ जाता। यह बैक-टेस्ट है, असली चेतावनी नहीं।'
                : 'Pukaar’s rules were run on the real forecasts of the July 2023 flood: in Gohar, Watch would have come this many hours before the river’s highest day. This is a back-test, not a real alert.'}
            </p>
            <Link to="/impact" className="go-link">
              {hi ? 'सबूत देखें' : 'See the proof'} <ArrowRight aria-hidden="true" />
            </Link>
          </div>
        </div>
      </section>

      <section className="home-band" aria-labelledby="district-h">
        <div className="wrap home-split">
          <p className="home-num" aria-hidden="true">
            {PER_VILLAGE_SEASON}
          </p>
          <div>
            <h2 id="district-h" className="home-h2">
              {hi ? `${PER_VILLAGE_SEASON} प्रति गाँव, प्रति मानसून` : `${PER_VILLAGE_SEASON} per village, per monsoon`}
            </h2>
            <p className="home-para">
              {hi
                ? 'ज़िलों के लिए: कॉल, SMS और Telegram का अनुमानित ख़र्च, तैयारी की सूची और 90 दिन का पायलट।'
                : 'For districts: the estimated cost of calls, SMS and Telegram, the readiness list and a 90-day pilot.'}
            </p>
            <Link to="/pilot" className="go-link">
              {hi ? 'पायलट की योजना' : 'The pilot plan'} <ArrowRight aria-hidden="true" />
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
