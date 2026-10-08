/* Layout.jsx — top bar + severity banner row + bottom nav.
 * Hosts the routed screen via children. */

function Layout({ route, setRoute, isOnline, toggleOnline, queueCount, flashSynced, children }) {
  const navItems = [
    { id: 'dashboard', label: 'Dashboard',     icon: <Icon.Activity size={20} /> },
    { id: 'report',    label: 'Report',        icon: <Icon.FileText size={20} /> },
    { id: 'queue',     label: `Queue (${queueCount})`, icon: <Icon.UploadCloud size={20} /> },
    { id: 'settings',  label: 'Runtime',       icon: <Icon.Settings size={20} /> },
  ];

  return (
    <div className="app-shell">
      <header className="appbar">
        <h1><Icon.Activity size={22} /> Pukaar</h1>
        <button
          className={`connectivity-pill ${isOnline ? '' : 'is-offline'}`}
          onClick={toggleOnline}
        >
          {isOnline ? <><Icon.Wifi size={14} /> Online</> : <><Icon.WifiOff size={14} /> Offline</>}
        </button>
      </header>

      {!isOnline && (
        <Banner kind="offline">
          <Icon.Siren size={14} />
          SIN CONECTIVIDAD — operación local activa · cola: {queueCount}
        </Banner>
      )}
      {flashSynced && (
        <Banner kind="synced">
          <Icon.CheckCircle2 size={14} /> Sincronizado
        </Banner>
      )}

      <main className="page">{children}</main>

      <nav className="bottom-nav">
        {navItems.map((item) => (
          <a
            key={item.id}
            className={route === item.id ? 'is-active' : ''}
            onClick={() => setRoute(item.id)}
          >
            {item.icon}
            <span>{item.label}</span>
          </a>
        ))}
      </nav>
    </div>
  );
}

Object.assign(window, { Layout });
