import { useMemo, useState } from 'react';
import { FileUp, Pencil, Trash2, UserPlus } from 'lucide-react';
import { ApiError } from '../../api';
import { ConfirmDialog } from '../../components/ConfirmDialog';
import { DeniedNote, ErrorState, Skeleton } from '../../components/States';
import { usePoll } from '../../hooks/usePoll';
import { useT } from '../../i18n';
import {
  attestable,
  reachApi,
  todayIst,
  type ConsentInput,
  type Household,
  type HouseholdInput,
  type ImportPreview,
} from '../../lib/reach';
import { useConsole } from './consoleContext';
import { Page } from './Sections';
import '../../styles/reach.css';

/*
 * Enrolment (backend services/enrolment.py): EWS1294's lesson is that enrolment, not the phone, is what leaves
 * people out. An officer (their district) or a pradhan (their own village) adds or edits a household after reading
 * the notice aloud, or imports a vetted panchayat or patwari list: a preview first, then only the rows whose consent
 * they attest are stored. Numbers come back masked; every change is in the audit trail.
 */

const ROLES = ['villager', 'pradhan', 'gauge_reader', 'task_force'] as const;
const ROLE: Record<string, { en: string; hi: string }> = {
  villager: { en: 'Villager', hi: 'ग्रामीण' },
  pradhan: { en: 'Pradhan', hi: 'प्रधान' },
  gauge_reader: { en: 'Gauge reader', hi: 'गेज रीडर' },
  task_force: { en: 'Task force', hi: 'टास्क फ़ोर्स' },
  officer: { en: 'Officer', hi: 'अधिकारी' },
};
const METHOD: Record<string, { en: string; hi: string }> = {
  in_person: { en: 'Spoken, in person, after the notice', hi: 'आमने-सामने, सूचना सुनाने के बाद' },
  signed_form: { en: 'Signed or thumb-printed form', hi: 'हस्ताक्षर या अँगूठे वाला फ़ॉर्म' },
  phone_call: { en: 'Spoken on a phone call, after the notice', hi: 'फ़ोन पर, सूचना सुनाने के बाद' },
};
const GIVEN: Record<string, { en: string; hi: string }> = {
  self: { en: 'The person', hi: 'स्वयं' },
  family: { en: 'A family member', hi: 'परिवार का सदस्य' },
  guardian: { en: 'A guardian or carer', hi: 'अभिभावक या देखभाल करने वाले' },
};

const NOTICE_HI =
  'पुकार में जुड़ने पर हम आपका फ़ोन नंबर, आपका नाम (अगर बताएँ) और गाँव रखेंगे; केवल बाढ़ की चेतावनी, सब-ठीक और "आप सुरक्षित हैं?" के लिए कॉल करेंगे। जब तक आप जुड़े हैं तब तक; छोड़ने पर नंबर हटा दिया जाता है। छोड़ने के लिए प्रधान को बताएँ या सेवा के नंबर पर कॉल करके नौ दबाएँ।';
const NOTICE_EN =
  'Joining Pukaar, we keep your phone number, your name if you give it and your village, and call only for flood alerts, the all-clear and "are you safe?". Kept while you are enrolled; when you leave the number is deleted. To leave, tell the pradhan or call the service number and press 9.';

export default function Enrol() {
  const { lang } = useT();
  const hi = lang === 'hi';
  const c = useConsole();
  const villages = useMemo(
    () => (c.villages.data ?? []).filter((v) => c.officer || c.villageIds.includes(v.id)),
    [c.villages.data, c.officer, c.villageIds],
  );
  const [villageId, setVillageId] = useState('');
  const vid = villageId || villages[0]?.id || '';
  const list = usePoll(() => (vid ? reachApi.households(vid) : Promise.resolve(null)), [vid], 0);
  const [editing, setEditing] = useState<Household | null>(null);
  const [removing, setRemoving] = useState<Household | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);

  const remove = async () => {
    if (!removing) return;
    setErr(null);
    try {
      await reachApi.removeHousehold(vid, removing.id, 'removed in the console');
      list.refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setRemoving(null);
    }
  };

  return (
    <Page
      title={hi ? 'परिवार जोड़ें' : 'Enrol households'}
      lead={
        hi
          ? 'सूचना पढ़कर सुनाएँ, सहमति लें, फिर जोड़ें। हर बदलाव ऑडिट में दर्ज होता है; नंबर छिपे रहते हैं।'
          : 'Read the notice aloud, take consent, then enrol. Every change is audited; numbers stay masked.'
      }
      wide
    >
      <div className="enr">
        <label className="field">
          <span className="field-label">{hi ? 'गाँव' : 'Village'}</span>
          <select className="input-lg" value={vid} onChange={(e) => setVillageId(e.target.value)}>
            {villages.map((v) => (
              <option key={v.id} value={v.id}>
                {hi ? v.name_hi : v.name} ({v.district})
              </option>
            ))}
          </select>
        </label>
        {list.data?.ivr_code && (
          <p className="dp-meta">
            {hi ? `फ़ोन से जुड़ने का गाँव कोड: ${list.data.ivr_code}` : `Village code for joining by phone: ${list.data.ivr_code}`}
          </p>
        )}

        <details className="enr-sec" open>
          <summary>{hi ? 'सुनाने वाली सूचना' : 'The notice to read aloud'}</summary>
          <p lang="hi">{NOTICE_HI}</p>
          <p lang="en">{NOTICE_EN}</p>
        </details>

        <HouseholdForm
          key={editing?.id ?? 'new'}
          villageId={vid}
          editing={editing}
          onSaved={() => {
            setEditing(null);
            list.refresh();
          }}
          onCancel={() => setEditing(null)}
        />

        <section className="enr-sec" aria-labelledby="enr-list-h">
          <h2 id="enr-list-h" className="dp-sec-h">
            {hi ? 'जुड़े परिवार' : 'Enrolled households'} {list.data ? `(${list.data.households.length})` : ''}
          </h2>
          {err && (err.isDenied ? <DeniedNote error={err} /> : <ErrorState error={err} compact />)}
          {list.loading && !list.data ? (
            <Skeleton lines={3} />
          ) : list.error && !list.data ? (
            <ErrorState error={list.error} onRetry={list.refresh} compact />
          ) : (
            <div className="enr-table-wrap" tabIndex={0} role="region" aria-label={hi ? 'जुड़े परिवारों की तालिका' : 'Table of enrolled households'}>
              <table className="enr-table">
                <thead>
                  <tr>
                    <th scope="col">{hi ? 'नाम' : 'Name'}</th>
                    <th scope="col">{hi ? 'फ़ोन' : 'Phone'}</th>
                    <th scope="col">{hi ? 'भूमिका' : 'Role'}</th>
                    <th scope="col">{hi ? 'सहायता' : 'Assisted'}</th>
                    <th scope="col">{hi ? 'कैसे जुड़े' : 'Enrolled'}</th>
                    <th scope="col">
                      <span className="sr-only">{hi ? 'बदलें' : 'Actions'}</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {(list.data?.households ?? []).map((h) => (
                    <tr key={h.id}>
                      <td>{h.name}</td>
                      <td>{h.phone_masked ?? (hi ? 'टेलीग्राम' : 'Telegram')}</td>
                      <td>{(ROLE[h.role] ?? { en: h.role, hi: h.role })[lang]}</td>
                      <td>{h.assisted ? (hi ? 'हाँ' : 'yes') : '–'}</td>
                      <td title={h.consent ?? ''}>
                        {h.enrolled_via ?? 'telegram'}
                        {h.enrolled_by ? ` · ${h.enrolled_by}` : ''}
                      </td>
                      <td>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setEditing(h)} aria-label={`${hi ? 'बदलें' : 'Edit'} ${h.name}`}>
                          <Pencil aria-hidden="true" />
                        </button>
                        <button type="button" className="btn btn-ghost btn-sm" onClick={() => setRemoving(h)} aria-label={`${hi ? 'हटाएँ' : 'Remove'} ${h.name}`}>
                          <Trash2 aria-hidden="true" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <BulkImport key={vid} villageId={vid} onDone={list.refresh} />
      </div>
      <ConfirmDialog
        open={Boolean(removing)}
        title={hi ? `${removing?.name ?? ''} को हटाएँ?` : `Remove ${removing?.name ?? ''}?`}
        confirmLabel={hi ? 'हटाएँ' : 'Remove'}
        cancelLabel={hi ? 'रद्द' : 'Cancel'}
        tone="danger"
        onCancel={() => setRemoving(null)}
        onConfirm={() => void remove()}
      >
        <p>{hi ? 'उन्हें अब कोई चेतावनी नहीं मिलेगी; बचा रिकॉर्ड बाद में मिटा दिया जाता है।' : 'They get no more alerts; what is left of their record is erased later.'}</p>
      </ConfirmDialog>
    </Page>
  );
}

function ConsentFields({ value, onChange, idp }: { value: ConsentInput; onChange: (v: ConsentInput) => void; idp: string }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  return (
    <div className="enr-grid">
      <label className="field" htmlFor={`${idp}-method`}>
        <span className="field-label">{hi ? 'सहमति कैसे' : 'How consent was given'}</span>
        <select id={`${idp}-method`} value={value.method} onChange={(e) => onChange({ ...value, method: e.target.value })}>
          <option value="">{hi ? 'चुनें' : 'Choose'}</option>
          {Object.keys(METHOD).map((m) => (
            <option key={m} value={m}>
              {METHOD[m][lang]}
            </option>
          ))}
        </select>
      </label>
      <label className="field" htmlFor={`${idp}-given`}>
        <span className="field-label">{hi ? 'किसने दी' : 'Given by'}</span>
        <select id={`${idp}-given`} value={value.given_by} onChange={(e) => onChange({ ...value, given_by: e.target.value })}>
          {Object.keys(GIVEN).map((g) => (
            <option key={g} value={g}>
              {GIVEN[g][lang]}
            </option>
          ))}
        </select>
      </label>
      <label className="field" htmlFor={`${idp}-taken`}>
        <span className="field-label">{hi ? 'किसने ली (नाम)' : 'Taken by (name)'}</span>
        <input id={`${idp}-taken`} value={value.taken_by} onChange={(e) => onChange({ ...value, taken_by: e.target.value })} maxLength={80} />
      </label>
      <label className="field" htmlFor={`${idp}-date`}>
        <span className="field-label">{hi ? 'तारीख़' : 'Date'}</span>
        <input id={`${idp}-date`} type="date" value={value.date} onChange={(e) => onChange({ ...value, date: e.target.value })} />
      </label>
    </div>
  );
}

function HouseholdForm({ villageId, editing, onSaved, onCancel }: { villageId: string; editing: Household | null; onSaved: () => void; onCancel: () => void }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const c = useConsole();
  const [name, setName] = useState(editing?.name ?? '');
  const [phone, setPhone] = useState('');
  const [role, setRole] = useState(editing?.role ?? 'villager');
  const [assisted, setAssisted] = useState(editing?.assisted ?? false);
  const [consent, setConsent] = useState<ConsentInput>({ method: '', given_by: 'self', taken_by: c.username, date: todayIst() });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [done, setDone] = useState('');
  const needsConsent = !editing || phone.trim() !== '';

  const save = async () => {
    setBusy(true);
    setErr(null);
    setDone('');
    const body: HouseholdInput = { name: name.trim(), role, assisted };
    if (editing) body.recipient_id = editing.id;
    if (phone.trim()) body.phone = phone.trim();
    if (needsConsent || consent.method) body.consent = consent;
    try {
      const r = await reachApi.saveHousehold(villageId, body);
      setDone(r.created ? (hi ? 'जुड़ गए।' : 'Enrolled.') : hi ? 'बदलाव सहेजा।' : 'Saved.');
      setName('');
      setPhone('');
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="enr-sec"
      aria-labelledby="enr-form-h"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      <h2 id="enr-form-h" className="dp-sec-h">
        <UserPlus aria-hidden="true" /> {editing ? (hi ? `बदलें: ${editing.name}` : `Edit: ${editing.name}`) : hi ? 'एक परिवार जोड़ें' : 'Add a household'}
      </h2>
      <div className="enr-grid">
        <label className="field" htmlFor="enr-name">
          <span className="field-label">{hi ? 'नाम (वैकल्पिक)' : 'Name (optional)'}</span>
          <input id="enr-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
        </label>
        <label className="field" htmlFor="enr-phone">
          <span className="field-label">{hi ? 'मोबाइल नंबर' : 'Mobile number'}</span>
          <input
            id="enr-phone"
            inputMode="tel"
            autoComplete="off"
            value={phone}
            placeholder={editing?.phone_masked ?? '98xxxxxxxx'}
            onChange={(e) => setPhone(e.target.value)}
            required={!editing}
          />
        </label>
        <label className="field" htmlFor="enr-role">
          <span className="field-label">{hi ? 'भूमिका' : 'Role'}</span>
          <select id="enr-role" value={role} onChange={(e) => setRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {ROLE[r][lang]}
              </option>
            ))}
          </select>
        </label>
        <label className="enr-check">
          <input type="checkbox" checked={assisted} onChange={(e) => setAssisted(e.target.checked)} />
          {hi ? 'सहायता चाहिए (बुज़ुर्ग, दिव्यांग, अपना फ़ोन नहीं)' : 'Assisted (elderly, disabled, no phone of their own)'}
        </label>
      </div>
      {needsConsent && (
        <>
          <p className="dp-meta">{hi ? 'सहमति: सूचना सुनाने के बाद।' : 'Consent: after reading the notice aloud.'}</p>
          <ConsentFields value={consent} onChange={setConsent} idp="enr-c" />
        </>
      )}
      <div className="enr-actions">
        <button type="submit" className="btn btn-accent" disabled={busy || !villageId}>
          {editing ? (hi ? 'सहेजें' : 'Save') : hi ? 'जोड़ें' : 'Enrol'}
        </button>
        {editing && (
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            {hi ? 'रद्द' : 'Cancel'}
          </button>
        )}
      </div>
      {done && (
        <p className="dp-meta" role="status">
          {done}
        </p>
      )}
      {err && (err.isDenied ? <DeniedNote error={err} /> : <p className="dp-note is-bad" role="alert">{(hi && err.messageHi) || err.messageEn}</p>)}
    </form>
  );
}

const STATUS: Record<string, { en: string; hi: string }> = {
  ok: { en: 'ready', hi: 'तैयार' },
  duplicate: { en: 'duplicate in the file', hi: 'फ़ाइल में दोहराया' },
  exists: { en: 'already enrolled', hi: 'पहले से जुड़ा' },
  error: { en: 'error', hi: 'ग़लती' },
};

function BulkImport({ villageId, onDone }: { villageId: string; onDone: () => void }) {
  const { lang } = useT();
  const hi = lang === 'hi';
  const c = useConsole();
  const [csv, setCsv] = useState('');
  const [source, setSource] = useState('');
  const [att, setAtt] = useState<ConsentInput>({ method: 'in_person', given_by: 'self', taken_by: c.username, date: todayIst() });
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [attested, setAttested] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const changeCsv = (text: string) => {
    setCsv(text);
    setPreview(null);
    setAttested(new Set());
  };

  const run = async (commit: boolean) => {
    setBusy(true);
    setErr(null);
    try {
      const r = await reachApi.importHouseholds(villageId, { csv, commit, source, attested_rows: [...attested], attestation: att });
      setPreview(r);
      if (commit) {
        setAttested(new Set());
        onDone();
      }
    } catch (e) {
      setErr(e instanceof ApiError ? e : new ApiError(0, null));
    } finally {
      setBusy(false);
    }
  };
  const ok = preview ? attestable(preview.rows) : [];
  const toggle = (n: number, on: boolean) =>
    setAttested((s) => {
      const next = new Set(s);
      if (on) next.add(n);
      else next.delete(n);
      return next;
    });

  return (
    <section className="enr-sec" aria-labelledby="enr-imp-h">
      <h2 id="enr-imp-h" className="dp-sec-h">
        <FileUp aria-hidden="true" /> {hi ? 'पंचायत या पटवारी की सूची (CSV)' : 'A panchayat or patwari list (CSV)'}
      </h2>
      <p className="dp-meta">
        {hi
          ? 'स्तंभ: name, phone, assisted, consent method, given by, consent date। पहले जाँच होती है; कुछ भी तब तक नहीं जुड़ता जब तक आप हर पंक्ति की सहमति की पुष्टि न करें।'
          : 'Columns: name, phone, assisted, consent method, given by, consent date. A preview comes first; nothing is stored until you attest the consent of each row.'}
      </p>
      <label className="field" htmlFor="enr-file">
        <span className="field-label">{hi ? 'फ़ाइल चुनें' : 'Choose a file'}</span>
        <input
          id="enr-file"
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void f.text().then(changeCsv);
          }}
        />
      </label>
      <label className="field" htmlFor="enr-csv">
        <span className="field-label">{hi ? 'या यहाँ चिपकाएँ' : 'Or paste it here'}</span>
        <textarea id="enr-csv" rows={6} value={csv} onChange={(e) => changeCsv(e.target.value)} spellCheck={false} />
      </label>
      <div className="enr-grid">
        <label className="field" htmlFor="enr-source">
          <span className="field-label">{hi ? 'सूची का नाम' : 'Name of the list'}</span>
          <input id="enr-source" value={source} onChange={(e) => setSource(e.target.value)} placeholder="Panchayat household list 2026" maxLength={80} />
        </label>
      </div>
      <p className="dp-meta">{hi ? 'जिन पंक्तियों में सहमति नहीं लिखी, उनके लिए:' : 'For rows that do not say how consent was given:'}</p>
      <ConsentFields value={att} onChange={setAtt} idp="enr-att" />
      <div className="enr-actions">
        <button type="button" className="btn btn-ghost" disabled={busy || !csv.trim()} onClick={() => void run(false)}>
          {hi ? 'जाँचें' : 'Preview'}
        </button>
      </div>
      {err && (err.isDenied ? <DeniedNote error={err} /> : <p className="dp-note is-bad" role="alert">{(hi && err.messageHi) || err.messageEn}</p>)}
      {preview && (
        <>
          <p className="dp-meta" role="status">
            {hi
              ? `${preview.counts.ok} तैयार, ${preview.counts.duplicate} दोहराए, ${preview.counts.exists} पहले से, ${preview.counts.error} ग़लत`
              : `${preview.counts.ok} ready, ${preview.counts.duplicate} duplicates, ${preview.counts.exists} already enrolled, ${preview.counts.error} with errors`}
          </p>
          <div className="enr-table-wrap" tabIndex={0} role="region" aria-label={hi ? 'जाँच की तालिका' : 'Preview table'}>
            <table className="enr-table">
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">{hi ? 'नाम' : 'Name'}</th>
                  <th scope="col">{hi ? 'फ़ोन' : 'Phone'}</th>
                  <th scope="col">{hi ? 'स्थिति' : 'Status'}</th>
                  <th scope="col">{hi ? 'सहमति की पुष्टि' : 'Consent attested'}</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r) => (
                  <tr key={r.row}>
                    <td>{r.row}</td>
                    <td>{r.name || '–'}</td>
                    <td>{r.phone_masked}</td>
                    <td className={r.status === 'ok' ? 'is-ok' : 'is-bad'}>
                      {STATUS[r.status][lang]}
                      {r.errors.length > 0 && `: ${r.errors.join('; ')}`}
                    </td>
                    <td>
                      {r.status === 'ok' ? (
                        <label className="enr-check">
                          <input type="checkbox" checked={attested.has(r.row)} onChange={(e) => toggle(r.row, e.target.checked)} />
                          <span className="sr-only">{hi ? `पंक्ति ${r.row}` : `Row ${r.row}`}</span>
                          {hi ? 'हाँ' : 'Yes'}
                        </label>
                      ) : (
                        '–'
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="enr-actions">
            <button type="button" className="btn btn-ghost" disabled={!ok.length} onClick={() => setAttested(new Set(ok))}>
              {hi ? 'सभी तैयार पंक्तियों की पुष्टि' : 'Attest every ready row'}
            </button>
            <button type="button" className="btn btn-accent" disabled={busy || !attested.size || !source.trim()} onClick={() => void run(true)}>
              {hi ? `${attested.size} परिवार जोड़ें` : `Enrol ${attested.size} attested households`}
            </button>
          </div>
          {preview.result && (
            <p className="dp-meta" role="status">
              {hi
                ? `${preview.result.stored.length} जुड़े, ${preview.result.skipped.length} छोड़े गए।`
                : `${preview.result.stored.length} enrolled, ${preview.result.skipped.length} skipped.`}
            </p>
          )}
        </>
      )}
    </section>
  );
}
