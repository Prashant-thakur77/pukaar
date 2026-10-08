/* ReportForm.jsx — volunteer / operator report submission.
 * Mirrors frontend/src/pages/Report.tsx (cosmetic). */

function ReportForm({ sites, isOnline, onSubmit }) {
  const [siteId, setSiteId] = React.useState('');
  const [reporterName, setReporterName] = React.useState('');
  const [reporterRole, setReporterRole] = React.useState('Community Member');
  const [transcript, setTranscript] = React.useState('');
  const [photo, setPhoto] = React.useState(null);
  const [audio, setAudio] = React.useState(null);
  const [submitting, setSubmitting] = React.useState(false);

  const submit = (e) => {
    e.preventDefault();
    if (!siteId || !reporterName || !transcript) return;
    setSubmitting(true);
    setTimeout(() => {
      onSubmit({ site_id: siteId, reporter_name: reporterName, reporter_role: reporterRole, transcript_text: transcript, photo_attachment: photo, audio_attachment: audio });
      setSubmitting(false);
      setSiteId(''); setReporterName(''); setTranscript(''); setPhoto(null); setAudio(null);
    }, 400);
  };

  return (
    <>
      <div>
        <h1 style={{ fontSize: 20, fontWeight: 700 }}>New Observation</h1>
        <p style={{ color: 'var(--fg-3)', fontSize: 13, margin: '4px 0 0 0' }}>Submit a manual report for a monitored site.</p>
      </div>

      <form className="field-stack" onSubmit={submit}>
        <div>
          <FieldLabel required>Site</FieldLabel>
          <select className="field-select" value={siteId} onChange={(e) => setSiteId(e.target.value)} required>
            <option value="" disabled>Select a site</option>
            {sites.map((s) => <option key={s.id} value={s.id}>{s.name} ({s.region})</option>)}
          </select>
        </div>

        <div className="field-row">
          <div>
            <FieldLabel required>Your Name</FieldLabel>
            <input className="field-input" value={reporterName} onChange={(e) => setReporterName(e.target.value)}
              placeholder="e.g. Maria G." required />
          </div>
          <div>
            <FieldLabel>Role</FieldLabel>
            <select className="field-select" value={reporterRole} onChange={(e) => setReporterRole(e.target.value)}>
              <option>Community Member</option>
              <option>Local Official</option>
              <option>Emergency Responder</option>
            </select>
          </div>
        </div>

        <div>
          <FieldLabel required>Observation Transcript</FieldLabel>
          <div style={{ position: 'relative' }}>
            <textarea className="field-textarea" value={transcript} onChange={(e) => setTranscript(e.target.value)}
              placeholder="Describe the current water level, trends, and any affected areas..." required />
            <button type="button" className="mic-fab" title="Voice input (mock)"><Icon.Mic size={16} /></button>
          </div>
        </div>

        <div className="field-row">
          <div>
            <FieldLabel>Photo Evidence</FieldLabel>
            <input className="field-input" type="file" accept="image/*"
              onChange={(e) => setPhoto(e.target.files?.[0] ?? null)} style={{ padding: 8 }} />
            {photo && <div className="field-help">Queued photo: {photo.name}</div>}
          </div>
          <div>
            <FieldLabel>Audio Note</FieldLabel>
            <input className="field-input" type="file" accept="audio/*"
              onChange={(e) => setAudio(e.target.files?.[0] ?? null)} style={{ padding: 8 }} />
            {audio && <div className="field-help">Queued audio: {audio.name}</div>}
          </div>
        </div>

        <Button
          type="submit"
          variant={isOnline ? 'primary' : 'orange'}
          full
          disabled={submitting}
          icon={submitting ? null : (isOnline ? <Icon.Send size={18} /> : <Icon.Save size={18} />)}
        >
          {submitting ? 'Saving…' : isOnline ? 'Submit Report' : 'Save Offline'}
        </Button>
      </form>
    </>
  );
}

Object.assign(window, { ReportForm });
