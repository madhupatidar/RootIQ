import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  createException,
  errorMessage,
  getCommodities,
  getFilterOptions,
  getInvestigationQuestions,
  getTerminals,
  notesAssist,
  submitInvestigation,
  suggestProNumber,
} from '../api/client.js';
import NotesAssist from '../components/NotesAssist.jsx';
import useDebounced from '../lib/useDebounced.js';

const PACKAGE_TYPES = ['Carton', 'Skid', 'Crate', 'Bundle', 'Drum', 'Roll'];

const EMPTY_FORM = {
  pro_number: '',
  od400_pro: '',
  origin_terminal: '',
  destination_terminal: '',
  shipper_name: '',
  consignee_name: '',
  manifest_number: '',
  found_on: 'trailer',
  trailer_or_bay_number: '',
  bl_number: '',
  po_number: '',
  sn_number: '',
  hazmat: false,
  shrink_wrapped: true,
  handling_units: 1,
  commodity_code: '',
  package_type: 'Carton',
  pieces: 1,
  weight: '',
  item_carton_model_serial: '',
  value_range: 1,
  dollar_amount: '',
  manufacturer_brand: '',
  additional_details: '',
  entry_user: '',
  assigned_to: '',
};

/** Same shape the backend uses to build `combined_notes_text`, so the assist sees real input. */
const buildNotes = (questions, answers) =>
  questions
    .filter((q) => (answers[q.key]?.notes_text || '').trim())
    .map((q) => `${q.prompt} [${answers[q.key].answer_yn}] ${answers[q.key].notes_text.trim()}`)
    .join('\n');

export default function LogExceptionPage() {
  const navigate = useNavigate();
  const [form, setForm] = useState(EMPTY_FORM);
  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers] = useState({});
  const [commodities, setCommodities] = useState([]);
  const [terminals, setTerminals] = useState([]);
  const [options, setOptions] = useState({ terminals: [], commodity_codes: [], entry_users: [] });

  const [assist, setAssist] = useState(null);
  const [assistLoading, setAssistLoading] = useState(false);

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState(null);

  useEffect(() => {
    Promise.all([getInvestigationQuestions(), getCommodities(), getTerminals(), getFilterOptions()])
      .then(([qs, comms, terms, opts]) => {
        setQuestions(qs);
        setAnswers(Object.fromEntries(qs.map((q) => [q.key, { answer_yn: 'N', notes_text: '' }])));
        setCommodities(comms);
        setTerminals(terms);
        setOptions(opts);
      })
      .catch((err) => setError(errorMessage(err)));
    suggestProNumber()
      .then(({ pro_number }) => setForm((prev) => ({ ...prev, pro_number, od400_pro: pro_number })))
      .catch(() => {});
  }, []);

  const terminalOptions = useMemo(
    () => [...new Set([...terminals, ...options.terminals])].sort(),
    [terminals, options.terminals],
  );

  const commodityOptions = useMemo(() => {
    const known = new Set(commodities.map((c) => c.code));
    const extra = (options.commodity_codes ?? [])
      .filter((code) => !known.has(code))
      .map((code) => ({ code, description: '(not in master)' }));
    return [...commodities, ...extra];
  }, [commodities, options.commodity_codes]);

  // --- Tier 2: re-check the notes while they are being typed ------------------------------
  const notes = useMemo(() => buildNotes(questions, answers), [questions, answers]);
  const debouncedNotes = useDebounced(notes, 500);

  useEffect(() => {
    if (!debouncedNotes.trim()) {
      setAssist(null);
      return undefined;
    }
    const controller = new AbortController();
    setAssistLoading(true);
    notesAssist({ text: debouncedNotes }, { signal: controller.signal })
      .then(setAssist)
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      })
      .finally(() => setAssistLoading(false));
    return () => controller.abort();
  }, [debouncedNotes]);

  const update = (key) => (event) => {
    const value = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const setAnswer = (key, field) => (event) =>
    setAnswers((prev) => ({ ...prev, [key]: { ...prev[key], [field]: event.target.value } }));

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const payload = {
        ...form,
        od400_pro: form.od400_pro || form.pro_number,
        handling_units: Number(form.handling_units),
        pieces: Number(form.pieces),
        weight: Number(form.weight),
        value_range: Number(form.value_range),
        dollar_amount: form.dollar_amount === '' ? null : Number(form.dollar_amount),
        manifest_number: form.manifest_number || null,
        bl_number: form.bl_number || null,
        po_number: form.po_number || null,
        sn_number: form.sn_number || null,
        manufacturer_brand: form.manufacturer_brand || null,
        assigned_to: form.assigned_to || null,
      };
      const created = await createException(payload);

      const steps = questions
        .filter((q) => (answers[q.key]?.notes_text || '').trim())
        .map((q) => ({
          question_key: q.key,
          answer_yn: answers[q.key].answer_yn,
          notes_text: answers[q.key].notes_text.trim(),
        }));
      if (steps.length > 0) {
        await submitInvestigation(created.id, { steps, mark_complete: true });
      }

      setSubmitted({
        id: created.id,
        pro_number: created.pro_number,
        notesCaptured: steps.length,
      });
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const logAnother = async () => {
    setSubmitted(null);
    setForm(EMPTY_FORM);
    setAnswers(Object.fromEntries(questions.map((q) => [q.key, { answer_yn: 'N', notes_text: '' }])));
    setAssist(null);
    try {
      const { pro_number } = await suggestProNumber();
      setForm((prev) => ({ ...prev, pro_number, od400_pro: pro_number }));
    } catch {
      /* the clerk can type one */
    }
  };

  if (submitted) {
    return (
      <div className="panel success-panel">
        <span className="success-mark">✓</span>
        <h1>Exception {submitted.pro_number} logged</h1>
        <p className="success-lead">
          {submitted.notesCaptured} investigation step(s) captured.
        </p>
        <p className="muted">
          Root cause will be determined by classification — nothing here overrides that.
        </p>
        <div className="row">
          <Link to={`/exceptions/${submitted.id}`}>
            <button type="button">Open the exception</button>
          </Link>
          <button type="button" className="secondary" onClick={logAnother}>
            Log another
          </button>
          <button type="button" className="secondary" onClick={() => navigate('/exceptions')}>
            Back to list
          </button>
        </div>
      </div>
    );
  }

  return (
    <form onSubmit={submit}>
      <div className="page-head">
        <div>
          <h1>Log an OV exception</h1>
          <p className="subtitle">
            As you write the investigation, similar past cases are matched to suggest a draft root
            cause and show what the notes are still missing.
          </p>
        </div>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="grid-detail">
        <div>
          <div className="panel">
            <div className="panel-head">
              <h2>Shipment</h2>
              <span className="panel-hint">PRO must carry a valid mod-7 check digit</span>
            </div>
            <div className="form-grid">
              <label className="field">
                <span>PRO number</span>
                <input value={form.pro_number} onChange={update('pro_number')} required />
              </label>
              <label className="field">
                <span>OD400 PRO</span>
                <input value={form.od400_pro} onChange={update('od400_pro')} placeholder="same as PRO" />
              </label>
              <label className="field">
                <span>Origin terminal</span>
                <select value={form.origin_terminal} onChange={update('origin_terminal')} required>
                  <option value="">Select…</option>
                  {terminalOptions.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Destination terminal</span>
                <select value={form.destination_terminal} onChange={update('destination_terminal')} required>
                  <option value="">Select…</option>
                  {terminalOptions.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Shipper</span>
                <input value={form.shipper_name} onChange={update('shipper_name')} required />
              </label>
              <label className="field">
                <span>Consignee</span>
                <input value={form.consignee_name} onChange={update('consignee_name')} required />
              </label>
              <label className="field">
                <span>Found on</span>
                <select value={form.found_on} onChange={update('found_on')}>
                  <option value="trailer">Trailer</option>
                  <option value="bay">Bay</option>
                </select>
              </label>
              <label className="field">
                <span>Trailer / bay number</span>
                <input value={form.trailer_or_bay_number} onChange={update('trailer_or_bay_number')} required />
              </label>
              <label className="field">
                <span>Manifest</span>
                <input value={form.manifest_number} onChange={update('manifest_number')} />
              </label>
              <label className="field">
                <span>BOL</span>
                <input value={form.bl_number} onChange={update('bl_number')} />
              </label>
              <label className="field">
                <span>PO</span>
                <input value={form.po_number} onChange={update('po_number')} />
              </label>
              <label className="field">
                <span>SN</span>
                <input value={form.sn_number} onChange={update('sn_number')} />
              </label>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>Freight</h2>
            </div>
            <div className="form-grid">
              <label className="field">
                <span>Commodity</span>
                <select value={form.commodity_code} onChange={update('commodity_code')} required>
                  <option value="">Select…</option>
                  {commodityOptions.map((c) => (
                    <option key={c.code} value={c.code}>
                      {c.code} — {c.description}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Package type</span>
                <select value={form.package_type} onChange={update('package_type')}>
                  {PACKAGE_TYPES.map((p) => (
                    <option key={p} value={p}>{p}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span>Handling units</span>
                <input type="number" min="1" value={form.handling_units} onChange={update('handling_units')} />
              </label>
              <label className="field">
                <span>Pieces</span>
                <input type="number" min="1" value={form.pieces} onChange={update('pieces')} />
              </label>
              <label className="field">
                <span>Weight (lb)</span>
                <input type="number" min="1" step="any" value={form.weight} onChange={update('weight')} required />
              </label>
              <label className="field">
                <span>Value range</span>
                <select value={form.value_range} onChange={update('value_range')}>
                  <option value={1}>$0 – $250</option>
                  <option value={2}>$250 – $1,000</option>
                  <option value={3}>&gt; $1,000</option>
                </select>
              </label>
              <label className="field">
                <span>Dollar amount {Number(form.value_range) === 3 ? '(required)' : ''}</span>
                <input
                  type="number"
                  step="any"
                  value={form.dollar_amount}
                  onChange={update('dollar_amount')}
                  required={Number(form.value_range) === 3}
                />
              </label>
              <label className="field">
                <span>Manufacturer / brand</span>
                <input value={form.manufacturer_brand} onChange={update('manufacturer_brand')} />
              </label>
              <label className="field field-check">
                <input type="checkbox" checked={form.hazmat} onChange={update('hazmat')} />
                <span>Hazmat</span>
              </label>
              <label className="field field-check">
                <input type="checkbox" checked={form.shrink_wrapped} onChange={update('shrink_wrapped')} />
                <span>Shrink wrapped</span>
              </label>
              <label className="field field-wide">
                <span>Item / carton / model / serial</span>
                <input value={form.item_carton_model_serial} onChange={update('item_carton_model_serial')} />
              </label>
              <label className="field field-wide">
                <span>Additional details</span>
                <textarea rows={2} value={form.additional_details} onChange={update('additional_details')} />
              </label>
            </div>
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>Investigation</h2>
              <span className="panel-hint">This text is what the classifier reads</span>
            </div>
            {questions.map((q) => (
              <div className="question" key={q.key}>
                <div className="question-head">
                  <span>{q.prompt}</span>
                  <select
                    value={answers[q.key]?.answer_yn ?? 'N'}
                    onChange={setAnswer(q.key, 'answer_yn')}
                  >
                    <option value="Y">Y</option>
                    <option value="N">N</option>
                  </select>
                </div>
                <textarea
                  rows={2}
                  placeholder="What did you find?"
                  value={answers[q.key]?.notes_text ?? ''}
                  onChange={setAnswer(q.key, 'notes_text')}
                />
              </div>
            ))}
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>Who</h2>
            </div>
            <div className="form-grid">
              <label className="field">
                <span>Entry user</span>
                <input
                  list="entry-users"
                  value={form.entry_user}
                  onChange={update('entry_user')}
                  required
                />
                <datalist id="entry-users">
                  {(options.entry_users ?? []).slice(0, 200).map((u) => (
                    <option key={u} value={u} />
                  ))}
                </datalist>
              </label>
              <label className="field">
                <span>Assigned to</span>
                <input list="entry-users" value={form.assigned_to} onChange={update('assigned_to')} />
              </label>
            </div>
          </div>

          <div className="row">
            <button type="submit" disabled={busy}>
              {busy ? 'Logging…' : 'Log exception'}
            </button>
            <span className="muted">
              Classification runs separately — logging never invents a root cause.
            </span>
          </div>
        </div>

        <aside className="entry-aside">
          <NotesAssist result={assist} loading={assistLoading} />
        </aside>
      </div>
    </form>
  );
}
