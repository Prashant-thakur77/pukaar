/* AndroidSiteDetail.jsx — site detail with sample analysis + report form.
 * Mirrors SiteDetailScreen in ui/PukaarApp.kt. */

function AndroidSiteDetail({ site, analysis, isAnalyzing, isRefreshing, onAnalyzeSample, onRefreshHydromet, onSubmitReport, onBack }) {
  const [name, setName] = React.useState('');
  const [role, setRole] = React.useState('brigadista');
  const [transcript, setTranscript] = React.useState('');
  const [offline, setOffline] = React.useState(false);
  const [submitting, setSubmitting] = React.useState(false);

  const submit = () => {
    if (!name || !transcript) return;
    setSubmitting(true);
    setTimeout(() => {
      onSubmitReport({ name, role, transcript, offline });
      setName(''); setTranscript('');
      setSubmitting(false);
    }, 400);
  };

  return (
    <div style={{
      flex: 1, overflowY: 'auto',
      background: PUKAAR_PALETTE.sand, padding: 16,
      display: 'flex', flexDirection: 'column', gap: 12,
      fontFamily: ANDROID_FONT,
    }}>
      <button onClick={onBack} style={{
        alignSelf: 'flex-start', background: 'transparent', border: 'none',
        color: PUKAAR_PALETTE.river, padding: 0, fontSize: 13, cursor: 'pointer',
        fontFamily: ANDROID_FONT, fontWeight: 500,
      }}>
        ← Volver
      </button>

      <div>
        <div style={{ fontSize: 22, fontWeight: 700, color: PUKAAR_PALETTE.emerald }}>{site.name}</div>
        <div style={{ fontSize: 13, color: PUKAAR_PALETTE.meta, marginTop: 2 }}>{site.region}</div>
      </div>

      <AndroidCard>
        <div style={{ fontSize: 14, fontWeight: 600, color: PUKAAR_PALETTE.emerald, marginBottom: 8 }}>Análisis del clip demo</div>
        <div style={{ fontSize: 13, color: PUKAAR_PALETTE.meta, lineHeight: 1.5, marginBottom: 12 }}>
          Corre el clip fijo de USGS Silverado contra el backend real. Resultado: nivel de alerta + frame de evidencia con narración de Pukaar AI.
        </div>
        <AndroidPrimaryButton onClick={onAnalyzeSample} fullWidth>
          {isAnalyzing ? 'Analizando…' : '▶ Analizar clip demo'}
        </AndroidPrimaryButton>

        {analysis && (
          <div style={{
            marginTop: 14,
            background: '#FCF5E5', border: `1px solid ${PUKAAR_PALETTE.border}`,
            borderRadius: 12, padding: 12,
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: PUKAAR_PALETTE.clay, textTransform: 'uppercase' }}>
                Nivel: {analysis.alert.level}
              </span>
              <span style={{ fontSize: 11, color: PUKAAR_PALETTE.meta }}>
                {Math.round(analysis.alert.score * 100)}% · {analysis.observation.frames_analyzed} frames
              </span>
            </div>
            <div style={{ marginTop: 8, fontSize: 13, color: PUKAAR_PALETTE.ink, lineHeight: 1.5 }}>
              {analysis.alert.summary}
            </div>
            {analysis.observation.image_description && (
              <div style={{ marginTop: 10 }}>
                <AndroidAssistChip tone="river">
                  Analizado con Pukaar AI en este dispositivo
                </AndroidAssistChip>
                <div style={{ marginTop: 8, fontSize: 12, color: PUKAAR_PALETTE.meta, fontStyle: 'italic', lineHeight: 1.5 }}>
                  "{analysis.observation.image_description}"
                </div>
              </div>
            )}
          </div>
        )}
      </AndroidCard>

      <AndroidCard>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <div style={{ fontSize: 14, fontWeight: 600, color: PUKAAR_PALETTE.emerald }}>Hidromet</div>
          <button onClick={onRefreshHydromet} style={{
            background: 'transparent', border: 'none', color: PUKAAR_PALETTE.river,
            fontSize: 13, cursor: 'pointer', fontFamily: ANDROID_FONT, fontWeight: 500,
          }}>{isRefreshing ? 'Actualizando…' : 'Refrescar'}</button>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <div style={{ background: '#F8F1DD', borderRadius: 8, padding: 10 }}>
            <div style={{ fontSize: 11, color: PUKAAR_PALETTE.meta }}>Lluvia ahora</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: PUKAAR_PALETTE.emerald, marginTop: 2 }}>12.4 mm</div>
          </div>
          <div style={{ background: '#F8F1DD', borderRadius: 8, padding: 10 }}>
            <div style={{ fontSize: 11, color: PUKAAR_PALETTE.meta }}>Prob 12h</div>
            <div style={{ fontSize: 16, fontWeight: 600, color: PUKAAR_PALETTE.emerald, marginTop: 2 }}>68%</div>
          </div>
        </div>
      </AndroidCard>

      <AndroidCard>
        <div style={{ fontSize: 14, fontWeight: 600, color: PUKAAR_PALETTE.emerald, marginBottom: 10 }}>Reporte de voluntario</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <AndroidTextField label="Nombre" value={name} onChange={(e) => setName(e.target.value)} placeholder="Tu nombre" />
          <AndroidTextField label="Rol" value={role} onChange={(e) => setRole(e.target.value)} placeholder="brigadista" />
          <AndroidTextField
            label="Transcripción"
            value={transcript}
            onChange={(e) => setTranscript(e.target.value)}
            placeholder="Describe lo que ves: nivel del agua, dirección, infraestructura afectada…"
            multiline
            rows={4}
          />
          <AndroidSwitch checked={offline} onChange={() => setOffline(!offline)} label="Forzar envío diferido (cola offline)" />
          <div style={{ height: 4 }} />
          <AndroidPrimaryButton
            onClick={submit}
            fullWidth
            variant={offline ? 'clay' : 'filled'}
          >
            {submitting ? 'Guardando…' : (offline ? 'Guardar en cola' : 'Enviar reporte')}
          </AndroidPrimaryButton>
        </div>
      </AndroidCard>
    </div>
  );
}

Object.assign(window, { AndroidSiteDetail });
