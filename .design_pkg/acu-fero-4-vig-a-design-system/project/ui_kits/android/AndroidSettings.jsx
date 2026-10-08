/* AndroidSettings.jsx — server URL + backend connectivity switch.
 * Mirrors SettingsScreen in ui/PukaarApp.kt. */

function AndroidSettings({ serverUrl, setServerUrl, isOnline, setOnline }) {
  const [draft, setDraft] = React.useState(serverUrl);
  const dirty = draft !== serverUrl;

  return (
    <div style={{
      flex: 1, overflowY: 'auto',
      background: PUKAAR_PALETTE.sand, padding: 16,
      display: 'flex', flexDirection: 'column', gap: 12,
      fontFamily: ANDROID_FONT,
    }}>
      <div>
        <div style={{ fontSize: 22, fontWeight: 700, color: PUKAAR_PALETTE.emerald }}>Ajustes</div>
        <div style={{ fontSize: 13, color: PUKAAR_PALETTE.meta, marginTop: 2 }}>
          Configuración del backend y simulador de conectividad.
        </div>
      </div>

      <AndroidCard>
        <div style={{ fontSize: 14, fontWeight: 600, color: PUKAAR_PALETTE.emerald, marginBottom: 8 }}>
          URL del backend
        </div>
        <div style={{ fontSize: 12, color: PUKAAR_PALETTE.meta, lineHeight: 1.5, marginBottom: 12 }}>
          Emulador: <code style={{ fontFamily: 'JetBrains Mono, Consolas, monospace', background: '#F8F1DD', padding: '1px 6px', borderRadius: 4 }}>http://10.0.2.2:8000/api/</code><br/>
          Dispositivo físico: usa la IP LAN de tu máquina.
        </div>
        <AndroidTextField value={draft} onChange={(e) => setDraft(e.target.value)} />
        <div style={{ marginTop: 12, display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <AndroidPrimaryButton variant="text" onClick={() => setDraft(serverUrl)}>Cancelar</AndroidPrimaryButton>
          <AndroidPrimaryButton onClick={() => setServerUrl(draft)} variant={dirty ? 'filled' : 'tonal'}>
            Guardar URL
          </AndroidPrimaryButton>
        </div>
      </AndroidCard>

      <AndroidCard>
        <div style={{ fontSize: 14, fontWeight: 600, color: PUKAAR_PALETTE.emerald, marginBottom: 4 }}>
          Conectividad del backend
        </div>
        <div style={{ fontSize: 12, color: PUKAAR_PALETTE.meta, marginBottom: 12, lineHeight: 1.5 }}>
          Simulador. Apagar deja al app en operación local: nodo CV + cola offline siguen funcionando, los reportes esperan flush.
        </div>
        <AndroidSwitch checked={isOnline} onChange={() => setOnline(!isOnline)}
          label={isOnline ? 'Backend online — sincronizando' : 'Backend offline — operación local'} />
      </AndroidCard>

      <div style={{
        marginTop: 4, fontSize: 11, color: PUKAAR_PALETTE.meta, textAlign: 'center',
        lineHeight: 1.6,
      }}>
        Pukaar · v0.1 Project build<br/>
        Pukaar AI on-device via MediaPipe LLM Inference
      </div>
    </div>
  );
}

Object.assign(window, { AndroidSettings });
