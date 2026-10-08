/* AndroidQueue.jsx — pending offline reports.
 * Mirrors QueueScreen in ui/PukaarApp.kt. */

function AndroidQueue({ reports, onFlush, isFlushing, isOnline }) {
  return (
    <div style={{
      flex: 1, overflowY: 'auto',
      background: PUKAAR_PALETTE.sand, padding: 16,
      display: 'flex', flexDirection: 'column', gap: 12,
      fontFamily: ANDROID_FONT,
    }}>
      <div>
        <div style={{ fontSize: 22, fontWeight: 700, color: PUKAAR_PALETTE.emerald }}>Cola pendiente</div>
        <div style={{ fontSize: 13, color: PUKAAR_PALETTE.meta, marginTop: 2 }}>
          Reportes que esperan flush al backend.
        </div>
      </div>

      <AndroidPrimaryButton
        onClick={onFlush}
        fullWidth
        variant={isOnline ? 'filled' : 'tonal'}
      >
        {isFlushing ? 'Sincronizando…' : (isOnline ? '☁︎ Flush queue ahora' : '☁︎ Esperando conexión')}
      </AndroidPrimaryButton>

      {reports.length === 0 ? (
        <AndroidCard>
          <div style={{ fontSize: 13, color: PUKAAR_PALETTE.meta, textAlign: 'center', padding: 12 }}>
            Sin reportes en cola. Sincronizado.
          </div>
        </AndroidCard>
      ) : (
        reports.map((r) => (
          <AndroidCard key={r.id}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 8 }}>
              <div style={{ minWidth: 0, flex: 1 }}>
                <div style={{ fontSize: 14, fontWeight: 600, color: PUKAAR_PALETTE.emerald }}>{r.site_id}</div>
                <div style={{ fontSize: 11, color: PUKAAR_PALETTE.meta, marginTop: 2 }}>
                  {r.reporter_name} · {r.reporter_role}
                </div>
              </div>
              <AndroidAssistChip tone="clay">Pendiente</AndroidAssistChip>
            </div>
            <div style={{
              marginTop: 10, padding: 10, background: '#F8F1DD',
              borderRadius: 8, fontSize: 13, color: PUKAAR_PALETTE.ink,
              fontStyle: 'italic', lineHeight: 1.5,
            }}>
              "{r.transcript}"
            </div>
            <div style={{ marginTop: 10, fontSize: 11, color: PUKAAR_PALETTE.meta }}>
              Capturado {new Date(r.createdAt).toLocaleString()}
            </div>
          </AndroidCard>
        ))
      )}
    </div>
  );
}

Object.assign(window, { AndroidQueue });
