/* Dashboard.jsx — Active Alerts + Monitored Sites.
 * Mirrors frontend/src/pages/Dashboard.tsx. */

function Dashboard({ alerts, sites, isOnline, onOpenSite }) {
  return (
    <>
      <section>
        <h2 className="section-h2">
          <span style={{ color: 'var(--orange-cta)' }}><Icon.AlertTriangle size={20} /></span>
          Active Alerts
        </h2>
        {alerts.length === 0 ? (
          <div style={{
            padding: 16, background: 'var(--gray-50)', border: '1px solid var(--border)',
            borderRadius: 8, display: 'flex', alignItems: 'center', gap: 12, color: 'var(--fg-3)'
          }}>
            <span style={{ color: 'var(--green-cta)' }}><Icon.CheckCircle2 size={20} /></span>
            No active alerts at the moment.
          </div>
        ) : (
          <div style={{ display: 'grid', gap: 12 }}>
            {alerts.map((a) => <AlertCard key={a.id} alert={a} />)}
          </div>
        )}
      </section>

      <section>
        <h2 className="section-h2">
          <span style={{ color: 'var(--primary)' }}><Icon.MapPin size={20} /></span>
          Monitored Sites
        </h2>
        <div className="grid-2">
          {sites.map((s) => <SiteCard key={s.id} site={s} onOpen={() => onOpenSite(s.id)} />)}
          {sites.length === 0 && isOnline && (
            <div style={{ color: 'var(--fg-3)', fontSize: 13 }}>No sites found.</div>
          )}
          {sites.length === 0 && !isOnline && (
            <div style={{ color: 'var(--fg-3)', fontSize: 13 }}>Offline. Sites not loaded.</div>
          )}
        </div>
      </section>
    </>
  );
}

function AlertCard({ alert }) {
  return (
    <div className={`sev sev-${alert.level}`}>
      <span style={{ flexShrink: 0, marginTop: 2 }}><Icon.AlertTriangle size={20} /></span>
      <div style={{ minWidth: 0 }}>
        <h3>{alert.site_id}</h3>
        <p>{alert.summary}</p>
        <div className="sev-meta">
          <span>Score: {Math.round(alert.score * 100)}%</span>
          {alert.trigger_source && <span>Source: {alert.trigger_source}</span>}
        </div>
        {alert.reasoning_summary && (
          <details>
            <summary>Razonamiento de Pukaar AI ({alert.reasoning_model ?? 'local'})</summary>
            <p>{alert.reasoning_summary}</p>
          </details>
        )}
      </div>
    </div>
  );
}

function SiteCard({ site, onOpen }) {
  return (
    <div className="card-base site-card" onClick={onOpen}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 16 }}>
        <div>
          <h3 className="site-card-title">{site.name}</h3>
          <p className="site-card-region">{site.region}</p>
          {site.description && <p className="site-card-desc">{site.description}</p>}
        </div>
        <Badge tone={site.is_active ? 'green' : 'gray'}>
          {site.is_active ? 'Active' : 'Inactive'}
        </Badge>
      </div>
      <div className="site-card-cta">
        Open site <Icon.ArrowRight size={14} />
      </div>
    </div>
  );
}

Object.assign(window, { Dashboard, AlertCard, SiteCard });
