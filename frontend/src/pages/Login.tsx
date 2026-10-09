import { useState, type FormEvent } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { LoaderCircle, LogIn, ShieldCheck, UserRound } from 'lucide-react';
import { api, ApiError, cognitoEnabled, cognitoSignIn } from '../api';
import { ErrorState } from '../components/States';
import { useT, type Key } from '../i18n';
import { useAuth } from '../store';

const DEMO: { username: string; label: Key }[] = [
  { username: 'officer1', label: 'login.demo.officer1' },
  { username: 'officer2', label: 'login.demo.officer2' },
  { username: 'pradhan_thunag', label: 'login.demo.pradhan' },
];

export default function Login() {
  const { t } = useT();
  const nav = useNavigate();
  const loc = useLocation();
  const signIn = useAuth((s) => s.signIn);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const next = (loc.state as { from?: string } | null)?.from ?? '/console';

  async function finish(token: string, fallbackUser: string) {
    useAuth.setState({ token });
    try {
      const me = await api.me();
      signIn(token, { username: me.username, role: me.role, village_ids: me.village_ids ?? [] });
    } catch {
      signIn(token, { username: fallbackUser, role: 'officer', village_ids: [] });
    }
    nav(next, { replace: true });
  }

  async function dev(u: string) {
    setBusy(u);
    setError(null);
    try {
      const res = await api.devLogin(u);
      await finish(res.token, res.username);
    } catch (e) {
      useAuth.getState().signOut();
      setError(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(null);
    }
  }

  async function cognito(e: FormEvent) {
    e.preventDefault();
    setBusy('cognito');
    setError(null);
    try {
      const token = await cognitoSignIn(username, password);
      await finish(token, username);
    } catch (err) {
      useAuth.getState().signOut();
      setError(err instanceof ApiError ? err : new ApiError(0, null));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="login">
      <section className="login-art" aria-hidden="true">
        <div className="login-rings">
          <i />
          <i />
          <i />
        </div>
        <p lang="hi" className="login-art-word">
          पुकार
        </p>
      </section>
      <section className="login-panel">
        <div className="login-box">
          <span className="login-badge" aria-hidden="true">
            <ShieldCheck />
          </span>
          <h1 className="display-3">{t('login.title')}</h1>
          <p className="muted">{t('login.lead')}</p>

          {cognitoEnabled ? (
            <form className="stack" onSubmit={cognito}>
              <label className="field">
                <span className="field-label">{t('login.username')}</span>
                <input className="input-lg" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
              </label>
              <label className="field">
                <span className="field-label">{t('login.password')}</span>
                <input className="input-lg" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" required />
              </label>
              <button type="submit" className="btn btn-lg btn-accent btn-block btn-press" disabled={busy !== null}>
                {busy ? <LoaderCircle className="spin" aria-hidden="true" /> : <LogIn aria-hidden="true" />} {t('login.submit')}
              </button>
            </form>
          ) : (
            <div className="stack">
              <p className="eyebrow">{t('login.demo')}</p>
              <ul className="demo-users">
                {DEMO.map((d) => (
                  <li key={d.username}>
                    <button type="button" className="demo-user btn-press" onClick={() => void dev(d.username)} disabled={busy !== null}>
                      <span className="du-icon" aria-hidden="true">
                        {busy === d.username ? <LoaderCircle className="spin" /> : <UserRound />}
                      </span>
                      <span className="du-text">
                        <strong>{d.username}</strong>
                        <span className="small muted">{t(d.label)}</span>
                      </span>
                      <LogIn aria-hidden="true" className="du-go" />
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {error && <ErrorState error={error} compact />}
          <p className="small muted">{t('login.public')}</p>
        </div>
      </section>
    </div>
  );
}
