import { useT } from '../../i18n';
import { Ask } from './Ask';
import { useConsole } from './consoleContext';
import { Page } from './Sections';

/** Ask Pukaar, a chunk of its own: the analyst's code loads only when an officer opens it. */
export default function AskSection() {
  const { t } = useT();
  const c = useConsole();
  return (
    <Page title={t('console.ask')}>
      <Ask villages={c.villages.data ?? []} />
    </Page>
  );
}
