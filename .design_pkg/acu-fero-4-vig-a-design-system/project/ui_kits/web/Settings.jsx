/* Settings.jsx — Runtime status (LLM + hydromet).
 * Mirrors frontend/src/pages/Settings.tsx (cosmetic). */

function Settings({ runtime }) {
  return (
    <>
      <div>
        <h1 style={{ fontSize: 24, lineHeight: '32px', fontWeight: 700 }}>Runtime Status</h1>
        <p style={{ color: 'var(--fg-3)', fontSize: 13, margin: '4px 0 0 0' }}>
          Browser-first MVP with local LLM adapter plus live hydromet enrichment.
        </p>
      </div>

      <section className="grid-2">
        <div className="card-lg">
          <h3 className="h3-row">
            <span style={{ color: 'var(--primary)' }}><Icon.Cpu size={20} /></span>
            Pukaar AI runtime
          </h3>
          {runtime ? (
            <div style={{ marginTop: 16, display: 'grid', gap: 10, fontSize: 13, color: 'var(--fg-2)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {runtime.llm.reachable
                  ? <span style={{ color: '#16A34A' }}><Icon.CheckCircle2 size={16} /></span>
                  : <span style={{ color: '#DC2626' }}><Icon.ServerCrash size={16} /></span>}
                <span>{runtime.llm.reachable ? 'LLM endpoint reachable' : 'LLM endpoint not reachable'}</span>
              </div>
              <div><span style={{ color: 'var(--fg-3)' }}>Enabled:</span> {runtime.llm.enabled ? 'Yes' : 'No'}</div>
              <div><span style={{ color: 'var(--fg-3)' }}>Base URL:</span> {runtime.llm.base_url}</div>
              <div><span style={{ color: 'var(--fg-3)' }}>Model:</span> {runtime.llm.model}</div>
              <div><span style={{ color: 'var(--fg-3)' }}>Detail:</span> {runtime.llm.detail}</div>
            </div>
          ) : (
            <p style={{ fontSize: 13, color: 'var(--fg-3)', marginTop: 16 }}>Loading runtime status…</p>
          )}
        </div>

        <div className="card-lg">
          <h3 className="h3-row">
            <span style={{ color: 'var(--accent-cyan)' }}><Icon.Waves size={20} /></span>
            Hydromet provider
          </h3>
          {runtime ? (
            <div style={{ marginTop: 16, display: 'grid', gap: 10, fontSize: 13, color: 'var(--fg-2)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {runtime.hydromet.reachable
                  ? <span style={{ color: '#16A34A' }}><Icon.CheckCircle2 size={16} /></span>
                  : <span style={{ color: '#DC2626' }}><Icon.ServerCrash size={16} /></span>}
                <span>{runtime.hydromet.reachable ? 'Provider reachable' : 'Provider not reachable'}</span>
              </div>
              <div><span style={{ color: 'var(--fg-3)' }}>Enabled:</span> {runtime.hydromet.enabled ? 'Yes' : 'No'}</div>
              <div><span style={{ color: 'var(--fg-3)' }}>Detail:</span> {runtime.hydromet.detail}</div>
              <div><span style={{ color: 'var(--fg-3)' }}>Backend connectivity toggle:</span> {runtime.is_online ? 'Online' : 'Offline'}</div>
            </div>
          ) : (
            <p style={{ fontSize: 13, color: 'var(--fg-3)', marginTop: 16 }}>Loading provider status…</p>
          )}
        </div>
      </section>

      <section className="card-lg">
        <h3 className="h3-row">Recommended local Pukaar AI setup</h3>
        <p style={{ fontSize: 13, color: 'var(--fg-2)', margin: '10px 0 14px 0', lineHeight: 1.6 }}>
          For a 12 GB VRAM box, start with <code style={{ fontFamily: 'var(--font-mono)', background: 'var(--gray-100)', padding: '1px 6px', borderRadius: 4 }}>pukaar-model:2b</code> and move to{' '}
          <code style={{ fontFamily: 'var(--font-mono)', background: 'var(--gray-100)', padding: '1px 6px', borderRadius: 4 }}>pukaar-ai4:e4b</code> only if latency and VRAM stay acceptable.
          The backend defaults to Ollama's OpenAI-compatible endpoint on <code style={{ fontFamily: 'var(--font-mono)', background: 'var(--gray-100)', padding: '1px 6px', borderRadius: 4 }}>127.0.0.1:11434/v1</code>.
        </p>
        <pre className="mono-block">{`PUKAAR_LLM_ENABLED=true
PUKAAR_LLM_BASE_URL=http://127.0.0.1:11434/v1
PUKAAR_LLM_MODEL=pukaar-model:2b
PUKAAR_LLM_API_KEY=ollama`}</pre>
        <p style={{ fontSize: 13, color: 'var(--fg-2)', margin: '14px 0 0 0', lineHeight: 1.6 }}>
          Use <code style={{ fontFamily: 'var(--font-mono)', background: 'var(--gray-100)', padding: '1px 6px', borderRadius: 4 }}>./scripts/run_pukaar-ai_local.sh</code> from the repo root to install Ollama, start the server and pull the selected Pukaar AI model.
          If the local model is down, the backend falls back to rule-based parsing so field reports still work.
        </p>
      </section>
    </>
  );
}

Object.assign(window, { Settings });
