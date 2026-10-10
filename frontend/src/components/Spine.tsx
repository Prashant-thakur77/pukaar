import { CalendarClock, CheckCheck, FileText, Gauge, MessageCircleHeart, Volume2 } from 'lucide-react';
import { Reveal } from './Reveal';
import { useT } from '../i18n';

type Bi = { hi: string; en: string };
interface Link {
  icon: typeof Gauge;
  step: Bi;
  what: Bi;
  aws: string;
}

/** The loop as one chain, each link with the AWS service that does the work. */
const LINKS: Link[] = [
  {
    icon: CalendarClock,
    step: { hi: 'हर 15 मिनट', en: 'Every 15 min' },
    what: { hi: 'बारिश और नदी के पूर्वानुमान पढ़ना', en: 'Read rain and river forecasts' },
    aws: 'EventBridge Scheduler · Lambda',
  },
  {
    icon: Gauge,
    step: { hi: 'नियम', en: 'Rules' },
    what: { hi: 'कोड स्तर तय करता है, मॉडल नहीं', en: 'Code sets the level, never the model' },
    aws: 'Lambda · DynamoDB',
  },
  {
    icon: FileText,
    step: { hi: 'मसौदा', en: 'Draft' },
    what: { hi: 'तय हिंदी साँचे में संदेश; जाँच हर संख्या परखती है', en: 'Fixed Hindi template; a checker verifies every number' },
    aws: 'Bedrock (Nova) · Strands · Cedar',
  },
  {
    icon: CheckCheck,
    step: { hi: 'मंज़ूरी', en: 'Approve' },
    what: { hi: 'अधिकारी एक टैप से मंज़ूर करता है; जवाब नहीं तो अगला अधिकारी', en: 'An officer approves with one tap; no answer, the next officer' },
    aws: 'Step Functions · Cognito',
  },
  {
    icon: Volume2,
    step: { hi: 'आवाज़', en: 'Speak' },
    what: { hi: 'हिंदी में बोली गई चेतावनी हर फ़ोन पर', en: 'A spoken Hindi alert to every phone' },
    aws: 'Polly · S3 · Telegram',
  },
  {
    icon: MessageCircleHeart,
    step: { hi: 'सुना गया', en: 'Heard' },
    what: { hi: '"मिल गया" से पुष्टि; नहीं तो दोबारा', en: 'Confirmed with "मिल गया"; if not, sent again' },
    aws: 'API Gateway · DynamoDB · CloudWatch',
  },
];

export function Spine() {
  const { t, lang } = useT();
  return (
    <section className="band band-paper-2 spine" aria-labelledby="spine-title">
      <div className="wrap">
        <Reveal variant="slide">
          <p className="eyebrow">{t('spine.eyebrow')}</p>
          <h2 id="spine-title" className="display-2">
            {t('spine.title')}
          </h2>
        </Reveal>
        <ol className="spine-chain">
          {LINKS.map((l, i) => (
            <Reveal as="li" key={l.aws} delay={i * 70} className="spine-link">
              <span className="spine-icon" aria-hidden="true">
                <l.icon />
              </span>
              <span className="spine-step" lang={lang}>
                {l.step[lang]}
              </span>
              <span className="spine-what" lang={lang}>
                {l.what[lang]}
              </span>
              <span className="spine-aws">{l.aws}</span>
            </Reveal>
          ))}
        </ol>
        <p className="spine-note small muted">{t('spine.note')}</p>
      </div>
    </section>
  );
}
