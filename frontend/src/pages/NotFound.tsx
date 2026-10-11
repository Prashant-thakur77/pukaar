import { Link } from 'react-router-dom';
import { EmptyState } from '../components/States';
import { useT } from '../i18n';

export default function NotFound() {
  const { t } = useT();
  return (
    <div className="wrap nf">
      <EmptyState word="404" title={t('notfound.title')} action={<Link to="/" className="btn btn-ink">{t('nav.home')}</Link>} />
    </div>
  );
}
