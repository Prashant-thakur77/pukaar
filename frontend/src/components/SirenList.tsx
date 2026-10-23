import { BellRing, Info } from 'lucide-react';
import { useT } from '../i18n';
import { fmtAgo, fmtTime } from '../lib/format';
import { healthChip, kindWord, pathWord, st, type DeviceTest, type PublicDevice } from '../lib/sirens';
import type { Lang } from '../store';
import '../sirens.css';

function testText(silent: DeviceTest | null | undefined, audible: DeviceTest | null | undefined, lang: Lang) {
  const latest = [
    silent ? { kind: 'silent' as const, t: silent } : null,
    audible ? { kind: 'audible' as const, t: audible } : null,
  ]
    .filter((x): x is { kind: 'silent' | 'audible'; t: DeviceTest } => Boolean(x))
    .sort((a, b) => b.t.at.localeCompare(a.t.at))[0];
  if (!latest) return { text: st(lang, 'test.none'), bad: true };
  const ok = latest.t.ok === true;
  return {
    text: `${st(lang, latest.kind === 'silent' ? 'test.silent' : 'test.audible')}, ${fmtTime(latest.t.at, lang)}: ${st(lang, ok ? 'test.ok' : 'test.failed')}`,
    bad: !ok,
  };
}

/** /how#sensors: every registered siren, pradhan box and relay, with health that fails closed. */
export function SirenList({ devices, names }: { devices?: PublicDevice[] | null; names: Map<string, string> }) {
  const { lang } = useT();
  const list = devices ?? [];
  return (
    <section className="siren-band" aria-labelledby="sn-sirens-h">
      <div>
        <h3 id="sn-sirens-h" className="xp-h3">
          {st(lang, 'list.title')}
        </h3>
        <p className="sn-honest">
          <Info aria-hidden="true" />
          {st(lang, 'list.honest')}
        </p>
        {list.length === 0 ? (
          <p className="small muted">{st(lang, 'list.empty')}</p>
        ) : (
          <ul className="siren-list">
            {list.map((d) => {
              const chip = healthChip(d.health, lang);
              const test = testText(d.last_test_silent, d.last_test_audible, lang);
              const sound = d.last_sound;
              return (
                <li key={d.device_id} className="siren-card">
                  <header className="siren-card-head">
                    <div>
                      <h3 className="siren-card-name">
                        <BellRing aria-hidden="true" /> {kindWord(d.kind, lang)} · {names.get(d.village_id) ?? d.village_id}
                      </h3>
                      <p className="small muted siren-id">{d.device_id}</p>
                    </div>
                    <div className="chip-row">
                      <span className={`chip ${chip.cls}`}>{chip.label}</span>
                      {d.simulated && <span className="chip chip-replay">{st(lang, 'simulated')}</span>}
                    </div>
                  </header>
                  <dl className="siren-facts">
                    <div>
                      <dt>{st(lang, 'state.label')}</dt>
                      <dd>{d.state ?? '—'}</dd>
                    </div>
                    <div>
                      <dt>{st(lang, 'seen.label')}</dt>
                      <dd>
                        {d.last_seen ? fmtAgo(d.last_seen, lang) : st(lang, 'seen.never')}
                        {d.last_seen && d.last_seen_path ? ` · ${pathWord(d.last_seen_path, lang)}` : ''}
                      </dd>
                    </div>
                    <div>
                      <dt>{st(lang, 'test.label')}</dt>
                      <dd className={test.bad ? 'bad-text' : 'ok-text'}>{test.text}</dd>
                    </div>
                    {sound?.at && (
                      <div>
                        <dt>{st(lang, 'sound.label')}</dt>
                        <dd className={sound.verified ? 'ok-text' : 'bad-text'}>
                          {fmtTime(sound.at, lang)}
                          {sound.pattern ? ` · ${sound.pattern}` : ''} ·{' '}
                          {st(lang, sound.verified ? 'sound.verified' : 'sound.unverified')}
                        </dd>
                      </div>
                    )}
                  </dl>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
