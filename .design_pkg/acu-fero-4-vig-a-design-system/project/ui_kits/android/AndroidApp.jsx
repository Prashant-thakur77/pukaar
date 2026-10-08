/* AndroidApp.jsx — palette + small atoms used across the volunteer-app screens.
 * Approximates Compose Material 3 visuals seen in ui/PukaarApp.kt. */

const PUKAAR_PALETTE = {
  emerald: '#0D3B2A',
  river:   '#1476B8',
  clay:    '#B45F22',
  sand:    '#F3E9D2',
  sand2:   '#EBE0C5',
  card:    '#FFFFFF',
  ink:     '#1A1A1A',
  meta:    '#5C5141',
  border:  '#D9CDB1',
};

const ANDROID_FONT = 'Roboto, "Segoe UI", system-ui, sans-serif';

// ---- Composite atoms ----

function AndroidCard({ children, style }) {
  return (
    <div style={{
      background: PUKAAR_PALETTE.card,
      borderRadius: 16,
      padding: 16,
      boxShadow: '0 1px 2px rgba(0,0,0,0.08), 0 1px 3px rgba(0,0,0,0.05)',
      ...style,
    }}>
      {children}
    </div>
  );
}

function AndroidStatusCard({ title, body }) {
  return (
    <AndroidCard>
      <div style={{ fontSize: 14, color: PUKAAR_PALETTE.meta, fontWeight: 500 }}>{title}</div>
      <div style={{ marginTop: 4, fontSize: 16, color: PUKAAR_PALETTE.ink, fontFamily: 'JetBrains Mono, Consolas, monospace' }}>
        {body}
      </div>
    </AndroidCard>
  );
}

function AndroidPrimaryButton({ children, onClick, fullWidth, variant = 'filled' }) {
  const palette = variant === 'clay' ? { bg: PUKAAR_PALETTE.clay, fg: '#FFFFFF' }
    : variant === 'tonal' ? { bg: '#DCE9F3', fg: PUKAAR_PALETTE.river }
    : variant === 'text' ? { bg: 'transparent', fg: PUKAAR_PALETTE.river }
    : { bg: PUKAAR_PALETTE.river, fg: '#FFFFFF' };
  return (
    <button onClick={onClick} style={{
      width: fullWidth ? '100%' : 'auto',
      background: palette.bg, color: palette.fg, border: 'none',
      padding: '10px 24px', borderRadius: 9999, fontFamily: ANDROID_FONT,
      fontSize: 14, fontWeight: 500, cursor: 'pointer',
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 8,
    }}>
      {children}
    </button>
  );
}

function AndroidAssistChip({ children, tone = 'neutral' }) {
  const tones = {
    neutral: { bg: '#FFFFFF', fg: PUKAAR_PALETTE.ink, bd: PUKAAR_PALETTE.border },
    river:   { bg: '#E8F1F8', fg: PUKAAR_PALETTE.river, bd: '#C5DCEC' },
    clay:    { bg: '#F8E6D6', fg: PUKAAR_PALETTE.clay, bd: '#E7CDB1' },
    emerald: { bg: '#D5E2DA', fg: PUKAAR_PALETTE.emerald, bd: '#B5C7BC' },
  };
  const t = tones[tone];
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      background: t.bg, color: t.fg, border: `1px solid ${t.bd}`,
      padding: '6px 12px', borderRadius: 8, fontSize: 12, fontWeight: 500,
      fontFamily: ANDROID_FONT,
    }}>
      {children}
    </span>
  );
}

function AndroidTextField({ label, value, onChange, multiline, placeholder, rows = 1 }) {
  const focused = false; // cosmetic — full focus state handled by browser
  return (
    <div style={{
      border: `1px solid ${focused ? PUKAAR_PALETTE.river : PUKAAR_PALETTE.border}`,
      borderRadius: 8, padding: '12px 14px', background: '#FFFFFFCC',
    }}>
      {label && <div style={{ fontSize: 11, color: PUKAAR_PALETTE.meta, marginBottom: 4, fontFamily: ANDROID_FONT, fontWeight: 500 }}>{label}</div>}
      {multiline ? (
        <textarea value={value} onChange={onChange} rows={rows}
          placeholder={placeholder}
          style={{
            width: '100%', border: 'none', outline: 'none', background: 'transparent',
            fontFamily: ANDROID_FONT, fontSize: 14, color: PUKAAR_PALETTE.ink, resize: 'none',
            padding: 0, lineHeight: 1.5,
          }}
        />
      ) : (
        <input value={value} onChange={onChange} placeholder={placeholder}
          style={{
            width: '100%', border: 'none', outline: 'none', background: 'transparent',
            fontFamily: ANDROID_FONT, fontSize: 14, color: PUKAAR_PALETTE.ink, padding: 0,
          }}
        />
      )}
    </div>
  );
}

function AndroidSwitch({ checked, onChange, label }) {
  return (
    <label style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', cursor: 'pointer', gap: 12 }}>
      <span style={{ fontFamily: ANDROID_FONT, fontSize: 14, color: PUKAAR_PALETTE.ink }}>{label}</span>
      <span
        onClick={onChange}
        style={{
          width: 52, height: 32, borderRadius: 9999,
          background: checked ? PUKAAR_PALETTE.river : '#C7BFA8',
          position: 'relative', transition: 'background 160ms ease',
          border: `2px solid ${checked ? PUKAAR_PALETTE.river : '#A8A08A'}`,
          boxSizing: 'border-box',
        }}>
        <span style={{
          position: 'absolute', top: 2, left: checked ? 22 : 2,
          width: 24, height: 24, borderRadius: '50%',
          background: '#FFFFFF', transition: 'left 160ms ease',
          boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
        }} />
      </span>
    </label>
  );
}

// ---- Bottom navigation (Material 3) ----
function AndroidBottomNav({ route, setRoute, queueCount }) {
  const items = [
    { id: 'dashboard', label: 'Dashboard', icon: '⟳' },
    { id: 'queue',     label: 'Queue',     icon: '☁︎', badge: queueCount > 0 ? queueCount : null },
    { id: 'settings',  label: 'Settings',  icon: '⚙' },
  ];
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-around',
      background: '#FFFFFF', borderTop: '1px solid ' + PUKAAR_PALETTE.border,
      paddingTop: 8, paddingBottom: 4,
    }}>
      {items.map((item) => {
        const active = route === item.id || (item.id === 'dashboard' && route === 'site-detail');
        return (
          <div key={item.id} onClick={() => setRoute(item.id)} style={{
            flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
            padding: '6px 0', cursor: 'pointer',
          }}>
            <div style={{
              width: 64, height: 32, borderRadius: 9999,
              background: active ? '#DCE9F3' : 'transparent',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: active ? PUKAAR_PALETTE.river : PUKAAR_PALETTE.meta,
              fontSize: 18, fontFamily: ANDROID_FONT, position: 'relative',
            }}>
              {item.icon}
              {item.badge != null && (
                <span style={{
                  position: 'absolute', top: 2, right: 14,
                  background: PUKAAR_PALETTE.clay, color: '#FFFFFF',
                  fontSize: 10, fontWeight: 600,
                  minWidth: 16, height: 16, borderRadius: 9999,
                  padding: '0 4px',
                  display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
                }}>{item.badge}</span>
              )}
            </div>
            <span style={{
              fontSize: 12, color: active ? PUKAAR_PALETTE.emerald : PUKAAR_PALETTE.meta,
              fontWeight: active ? 600 : 500, fontFamily: ANDROID_FONT,
            }}>{item.label}</span>
          </div>
        );
      })}
    </div>
  );
}

Object.assign(window, {
  PUKAAR_PALETTE, ANDROID_FONT,
  AndroidCard, AndroidStatusCard, AndroidPrimaryButton, AndroidAssistChip,
  AndroidTextField, AndroidSwitch, AndroidBottomNav,
});
