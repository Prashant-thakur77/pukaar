/* AndroidDashboard.jsx — dashboard screen.
 * Mirrors DashboardScreen in ui/PukaarApp.kt. */

function AndroidDashboard({ dashboard, queueCount, onOpenSite }) {
  return (
    <div style={{
      flex: 1, overflowY: 'auto',
      background: PUKAAR_PALETTE.sand, padding: 16,
      display: 'flex', flexDirection: 'column', gap: 12,
      fontFamily: ANDROID_FONT,
    }}>
      <div>
        <div style={{
          fontSize: 24, fontWeight: 700, color: PUKAAR_PALETTE.emerald, letterSpacing: '-0.01em',
        }}>Pukaar Pukaar Android</div>
        <div style={{ height: 6 }}/>
        <div style={{ fontSize: 13, color: PUKAAR_PALETTE.meta, lineHeight: 1.5 }}>
          MVP Android conectado al backend real, con queue offline y operaciones sobre el clip fijo demo.
        </div>
      </div>

      <AndroidStatusCard
        title="LLM"
        body={`${dashboard.runtime.llm.model} | reachable=${dashboard.runtime.llm.reachable}`}
      />
      <AndroidStatusCard
        title="Queue"
        body={`${queueCount} pendientes${queueCount === 0 ? ' · sincronizado' : ''}`}
      />
      <AndroidStatusCard
        title="Hydromet"
        body={`reachable=${dashboard.runtime.hydromet.reachable} · ${dashboard.runtime.hydromet.detail}`}
      />

      <div style={{
        marginTop: 8, fontSize: 12, fontWeight: 600, color: PUKAAR_PALETTE.meta,
        textTransform: 'uppercase', letterSpacing: '0.08em',
      }}>Sitios monitoreados</div>

      {dashboard.sites.map((site) => (
        <AndroidCard
          key={site.id}
          style={{ cursor: 'pointer' }}
        >
          <div onClick={() => onOpenSite(site.id)}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 16, fontWeight: 600, color: PUKAAR_PALETTE.emerald }}>{site.name}</div>
                <div style={{ fontSize: 12, color: PUKAAR_PALETTE.meta, marginTop: 2 }}>{site.region}</div>
              </div>
              <AndroidAssistChip tone={site.is_active ? 'emerald' : 'neutral'}>
                {site.is_active ? 'Activo' : 'Inactivo'}
              </AndroidAssistChip>
            </div>
            {site.last_alert && (
              <div style={{ marginTop: 12, display: 'flex', gap: 8, alignItems: 'center' }}>
                <span style={{
                  width: 8, height: 8, borderRadius: '50%',
                  background: site.last_alert === 'red' ? '#DC2626'
                    : site.last_alert === 'orange' ? '#F97316'
                    : site.last_alert === 'yellow' ? '#F59E0B'
                    : '#22C55E',
                  flexShrink: 0,
                }}/>
                <div style={{ fontSize: 12, color: PUKAAR_PALETTE.meta, textTransform: 'capitalize' }}>
                  Último estado: {site.last_alert}
                </div>
              </div>
            )}
          </div>
        </AndroidCard>
      ))}
    </div>
  );
}

Object.assign(window, { AndroidDashboard });
