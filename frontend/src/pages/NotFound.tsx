import { Link } from 'react-router-dom';
import { Kicker, ValleyLine } from '../components/Art';
import { useT } from '../i18n';

export default function NotFound() {
  const { t } = useT();
  return (
    <div className="wrap nf">
      <section className="nf-card" aria-labelledby="nf-title">
        <Kicker>404</Kicker>
        <h1 id="nf-title" className="nf-title">
          {t('notfound.title')}
        </h1>
        <Link to="/" className="btn btn-accent btn-lg">
          {t('nav.home')} →
        </Link>
        <ValleyLine quiet className="nf-valley" />
      </section>
    </div>
  );
}
