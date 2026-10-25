import { useT } from '../i18n';

/**
 * An alert's spoken Hindi text, exactly as villagers will hear it: the one Hindi an English page keeps, because
 * the officer has to check the words themselves. On a Hindi page it is simply the message. On an English page it
 * is marked as a quoted sample, with its English meaning under it.
 */
export function QuotedAlert({ hi, en }: { hi: string; en?: string | null }) {
  const { lang } = useT();
  if (lang === 'hi') return <blockquote className="dp-msg">{hi}</blockquote>;
  return (
    <div data-quoted-sample="">
      <p className="small muted">Spoken Hindi, word for word as villagers will hear it:</p>
      <blockquote className="dp-msg" lang="hi">
        {hi}
      </blockquote>
      {en && (
        <p className="small">
          <strong>In English:</strong> {en}
        </p>
      )}
    </div>
  );
}
