/* SiteDetail.jsx — hydromet + calibration + node analysis output.
 * Mirrors frontend/src/pages/SiteDetail.tsx (cosmetic). */

function SiteDetail({ site, snapshot, calibration, analysis, onBack, onRefreshHydromet, onAnalyzeSample, isRefreshing, isAnalyzingSample }) {
  if (!site) {
    return <div style={{ padding: 24, color: 'var(--fg-3)' }}>Loading site…</div>;
  }

  const criticalLineText = calibration?.critical_line?.length >= 2
    ? calibration.critical_line.map((p) => `(${p[0]}, ${p[1]})`).join(' → ')
    : 'Default line from backend';

  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <button className="btn btn-ghost" onClick={onBack} style={{ marginBottom: 12, padding: '6px 12px', fontSize: 12 }}>
            ← Back to dashboard
          </button>
          <h1 style={{ fontSize: 24, lineHeight: '32px', fontWeight: 700 }}>{site.name}</h1>
          <p style={{ color: 'var(--fg-3)', margin: '4px 0 0 0' }}>{site.region}</p>
          {site.description && <p style={{ fontSize: 13, color: 'var(--fg-2)', margin: '8px 0 0 0', maxWidth: 600 }}>{site.description}</p>}
        </div>
        <Button variant="ghost" icon={<Icon.Save size={16} />}>Adjust calibration</Button>
      </div>

      <section className="grid-asym">
        <div className="card-lg">
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, marginBottom: 16 }}>
            <div>
              <h3 className="h3-row">
                <span style={{ color: 'var(--primary)' }}><Icon.CloudRain size={20} /></span>
                Live hydromet context
              </h3>
              <p style={{ fontSize: 13, color: 'var(--fg-3)', margin: '6px 0 0 0' }}>Open-Meteo weather + flood snapshot.</p>
            </div>
            <Button variant="primary" onClick={onRefreshHydromet} disabled={isRefreshing}>
              {isRefreshing ? 'Refreshing…' : 'Refresh'}
            </Button>
          </div>

          {snapshot ? (
            <div style={{ display: 'grid', gap: 12, fontSize: 13, color: 'var(--fg-2)' }}>
              <div className="snapshot-hero">
                <div className="eyebrow">Signal score</div>
                <div className="value">{Math.round(snapshot.signal_score * 100)}%</div>
              </div>
              <div>{snapshot.summary}</div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div className="snapshot-tile">
                  <div className="label">Rain now</div>
                  <div className="value">{snapshot.precipitation_mm.toFixed(1)} mm</div>
                </div>
                <div className="snapshot-tile">
                  <div className="label">12h rain probability</div>
                  <div className="value">{snapshot.precipitation_probability.toFixed(0)}%</div>
                </div>
                <div className="snapshot-tile" style={{ gridColumn: '1 / -1' }}>
                  <div className="label">River discharge</div>
                  <div className="value">
                    {snapshot.river_discharge != null ? `${snapshot.river_discharge.toFixed(1)} m3/s` : 'Unavailable'}
                  </div>
                </div>
              </div>
            </div>
          ) : (
            <p style={{ fontSize: 13, color: 'var(--fg-3)' }}>No stored snapshot yet. Refresh to fetch live hydromet data.</p>
          )}
        </div>

        <div className="card-lg">
          <h3 className="h3-row">
            <span style={{ color: 'var(--accent-amber)' }}><Icon.Gauge size={20} /></span>
            Calibration summary
          </h3>
          <p style={{ fontSize: 13, color: 'var(--fg-3)', margin: '6px 0 16px 0' }}>The node analysis uses the latest stored ROI and threshold lines.</p>
          <div style={{ display: 'grid', gap: 12, fontSize: 13, color: 'var(--fg-2)' }}>
            <div>
              <div className="eyebrow">Critical line</div>
              <div className="mono" style={{ fontFamily: 'var(--font-mono)', fontSize: 12, marginTop: 4 }}>{criticalLineText}</div>
            </div>
            <div>
              <div className="eyebrow">Notes</div>
              <div style={{ marginTop: 4 }}>{calibration?.notes ?? 'No notes stored. Backend will fall back to defaults.'}</div>
            </div>
          </div>
        </div>
      </section>

      <section className="card-lg">
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap', marginBottom: 16 }}>
          <div>
            <h3 className="h3-row" style={{ marginBottom: 6 }}>
              <span style={{ color: 'var(--orange-cta)' }}><Icon.Upload size={20} /></span>
              Fixed-node video analysis
            </h3>
            <p style={{ fontSize: 13, color: 'var(--fg-3)', margin: 0, maxWidth: 540 }}>
              Upload a short fixed-camera clip or run the bundled site clip. The backend samples ~1 FPS,
              searches within the calibrated band and recomputes the fused site alert.
            </p>
          </div>
          <Button variant="soft-orange" onClick={onAnalyzeSample} disabled={isAnalyzingSample}
            icon={isAnalyzingSample ? <Icon.Loader size={16} className="spinner" /> : <Icon.PlayCircle size={16} />}>
            {isAnalyzingSample ? 'Running sample…' : 'Analyze bundled sample'}
          </Button>
        </div>

        {analysis && (
          <div className="grid-asym-rev" style={{ marginTop: 8 }}>
            <div style={{ display: 'grid', gap: 16 }}>
              <div className="snapshot-tile" style={{ background: 'var(--gray-50)' }}>
                <div style={{ fontWeight: 600, color: 'var(--fg-1)', marginBottom: 8, fontSize: 13 }}>Node metrics</div>
                <div style={{ fontSize: 13, color: 'var(--fg-2)', lineHeight: 1.7 }}>
                  <div>Frames analyzed: {analysis.observation.frames_analyzed}</div>
                  <div>Waterline ratio: {analysis.observation.waterline_ratio.toFixed(2)}</div>
                  <div>Rise velocity: {analysis.observation.rise_velocity.toFixed(4)}</div>
                  <div>Confidence: {Math.round(analysis.observation.confidence * 100)}%</div>
                  <div>Critical crossed: {analysis.observation.crossed_critical_line ? 'Yes' : 'No'}</div>
                </div>
              </div>
              <div className="snapshot-tile" style={{ background: 'var(--gray-50)' }}>
                <div style={{ fontWeight: 600, color: 'var(--fg-1)', marginBottom: 8, fontSize: 13 }}>Resulting alert</div>
                <div style={{ fontSize: 13, color: 'var(--fg-2)', lineHeight: 1.7 }}>
                  <div style={{ textTransform: 'capitalize' }}>Level: {analysis.alert.level}</div>
                  <div>Score: {Math.round(analysis.alert.score * 100)}%</div>
                  <div style={{ marginTop: 6 }}>{analysis.alert.summary}</div>
                </div>
                {analysis.alert.reasoning_summary && (
                  <details style={{
                    marginTop: 10, padding: 10, borderRadius: 6,
                    background: '#EFF6FF', border: '1px solid #BFDBFE',
                    color: '#1E3A8A', fontSize: 12
                  }}>
                    <summary style={{ cursor: 'pointer', fontWeight: 600, color: '#1E40AF' }}>
                      Razonamiento de Pukaar AI ({analysis.alert.reasoning_model ?? 'local'})
                    </summary>
                    <p style={{ margin: '8px 0 0 0', whiteSpace: 'pre-wrap' }}>{analysis.alert.reasoning_summary}</p>
                  </details>
                )}
              </div>
            </div>

            <EvidenceFrame analysis={analysis} />
          </div>
        )}
      </section>
    </>
  );
}

function EvidenceFrame({ analysis }) {
  // Cosmetic SVG stand-in for the bundled silverado_060s.jpg frame —
  // muddy turbid-water tones, ROI polygon, red critical line.
  return (
    <div style={{
      borderRadius: 12, overflow: 'hidden', border: '1px solid var(--border)',
      background: '#1F2937', position: 'relative', minHeight: 280
    }}>
      <div style={{ position: 'absolute', inset: 0, background: 'linear-gradient(180deg, #4A5568 0%, #2D3748 35%, #5B5234 60%, #6B5B3A 100%)' }}/>
      <svg viewBox="0 0 700 280" preserveAspectRatio="none" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
        <polygon points="60,150 640,150 620,260 80,260" fill="none" stroke="#22C55E" strokeWidth="2" strokeDasharray="6 4"/>
        <line x1="40" y1="120" x2="660" y2="120" stroke="#EF4444" strokeWidth="2"/>
        <text x="48" y="112" fontFamily="JetBrains Mono, monospace" fontSize="11" fill="#EF4444" fontWeight="600">critical line · y=120</text>
        <text x="68" y="172" fontFamily="JetBrains Mono, monospace" fontSize="10" fill="#22C55E">ROI · waterline 0.{Math.round(analysis.observation.waterline_ratio * 100).toString().padStart(2, '0')}</text>
      </svg>
      {analysis.observation.image_description && (
        <div style={{
          position: 'absolute', left: 0, right: 0, bottom: 0,
          background: 'rgba(0,0,0,0.7)', color: 'white',
          padding: '10px 16px', fontSize: 12, lineHeight: 1.5
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontWeight: 600 }}>
            <span>Pukaar AI ({analysis.observation.image_assessment_model ?? 'local'})</span>
            {typeof analysis.observation.image_assessment_confidence === 'number' && (
              <span>conf {Math.round(analysis.observation.image_assessment_confidence * 100)}%</span>
            )}
          </div>
          <div style={{ marginTop: 4, opacity: 0.95 }}>{analysis.observation.image_description}</div>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { SiteDetail, EvidenceFrame });
