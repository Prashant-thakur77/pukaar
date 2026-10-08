/* Queue.jsx — pending offline reports waiting to flush.
 * Mirrors frontend/src/pages/Queue.tsx (cosmetic). */

function Queue({ reports, isOnline, onFlush, onDelete, isFlushing }) {
  return (
    <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end', gap: 16 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700 }}>Sync Queue</h1>
          <p style={{ color: 'var(--fg-3)', fontSize: 13, margin: '4px 0 0 0' }}>Reports waiting to be sent.</p>
        </div>
        <Button
          variant="primary"
          icon={<Icon.UploadCloud size={16} />}
          onClick={onFlush}
          disabled={!isOnline || reports.length === 0 || isFlushing}
        >
          {isFlushing ? 'Sending…' : 'Sync Now'}
        </Button>
      </div>

      {!isOnline && reports.length > 0 && (
        <div style={{
          padding: 12, background: '#FFF7ED', border: '1px solid #FED7AA',
          borderRadius: 8, display: 'flex', alignItems: 'center', gap: 8,
          color: '#9A3412', fontSize: 13
        }}>
          <Icon.WifiOff size={16} />
          You are offline. Reports will sync when connection is restored.
        </div>
      )}

      {reports.length === 0 ? (
        <div className="empty-state">Queue is empty.</div>
      ) : (
        <div style={{ display: 'grid', gap: 12 }}>
          {reports.map((r) => (
            <div className="card-base queue-row" key={r.id}>
              <div className="row-top">
                <div>
                  <h3 className="site-card-title">Site ID: {r.site_id}</h3>
                  <p className="site-card-region">By {r.reporter_name} ({r.reporter_role})</p>
                </div>
                <button className="icon-btn" onClick={() => onDelete(r.id)} title="Delete from queue">
                  <Icon.Trash2 size={16} />
                </button>
              </div>
              <p className="queue-quote">"{r.transcript_text}"</p>
              {(r.photo_attachment || r.audio_attachment) && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {r.photo_attachment && <Badge tone="blue">Photo attached</Badge>}
                  {r.audio_attachment && <Badge tone="purple">Audio attached</Badge>}
                </div>
              )}
              <div style={{ fontSize: 11, color: 'var(--gray-400)' }}>
                Saved offline on: {new Date(r.createdAt).toLocaleString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

Object.assign(window, { Queue });
