import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  classifyException,
  clearException,
  errorMessage,
  getClearingCodes,
  getException,
  getHistory,
  getTaxonomy,
  overrideCategory,
} from '../api/client.js';
import SourceBadge from '../components/SourceBadge.jsx';
import { STATUS_LABELS, VALUE_RANGES, formatDate } from '../lib/format.js';

export default function ExceptionDetailPage() {
  const { id } = useParams();
  const [exception, setException] = useState(null);
  const [history, setHistory] = useState([]);
  const [taxonomy, setTaxonomy] = useState([]);
  const [clearingCodes, setClearingCodes] = useState([]);
  const [override, setOverride] = useState('');
  const [clearingCode, setClearingCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    try {
      const [detail, rows] = await Promise.all([getException(id), getHistory(id)]);
      setException(detail);
      setHistory(rows);
      setOverride(detail.latest_classification?.category || '');
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    Promise.all([getTaxonomy(), getClearingCodes()])
      .then(([tax, codes]) => {
        setTaxonomy(tax);
        setClearingCodes(codes);
      })
      .catch((err) => setError(errorMessage(err)));
  }, []);

  const run = async (action, successMessage) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      await action();
      await load();
      setNotice(successMessage);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!exception) {
    return <p className="muted">{error || 'Loading…'}</p>;
  }

  const latest = exception.latest_classification;

  return (
    <>
      <div className="row">
        <h1>Exception {exception.source_osd_number ?? '—'}</h1>
        <div className="spacer" />
        <Link to="/exceptions">← Back to list</Link>
      </div>
      <p className="subtitle">
        PRO {exception.pro_number} · {exception.origin_terminal} →{' '}
        {exception.destination_terminal} ·{' '}
        {STATUS_LABELS[exception.status] || exception.status}
        {exception.clearing_code ? ` · Cleared ${exception.clearing_code}` : ''}
      </p>

      {error && <p className="error">{error}</p>}
      {notice && <p className="muted">{notice}</p>}

      <div className="grid-detail">
        <div>
          <div className="panel">
            <h2>Investigation notes</h2>
            {exception.investigation ? (
              <>
                <div className="notes">{exception.investigation.combined_notes_text}</div>
                <details style={{ marginTop: 12 }}>
                  <summary>Step-by-step answers</summary>
                  <table style={{ marginTop: 8 }}>
                    <thead>
                      <tr><th>Question</th><th>Y/N</th><th>Notes</th></tr>
                    </thead>
                    <tbody>
                      {exception.investigation.steps.map((step, i) => (
                        <tr key={`${step.question_key}-${i}`}>
                          <td>{step.question_key}</td>
                          <td>{step.answer_yn}</td>
                          <td>{step.notes_text}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </details>
              </>
            ) : (
              <p className="muted">No investigation submitted yet.</p>
            )}
          </div>

          <div className="panel">
            <h2>Exception detail</h2>
            <dl className="kv">
              <dt>Shipper</dt><dd>{exception.shipper_name}</dd>
              <dt>Consignee</dt><dd>{exception.consignee_name}</dd>
              <dt>Found on</dt><dd>{exception.found_on} {exception.trailer_or_bay_number}</dd>
              <dt>Commodity / package</dt><dd>{exception.commodity_description || exception.commodity_code} · {exception.package_type}</dd>
              <dt>Pieces / weight</dt><dd>{exception.pieces} · {exception.weight} lb</dd>
              <dt>Handling units</dt><dd>{exception.handling_units}</dd>
              <dt>Hazmat</dt><dd>{exception.hazmat ? 'Yes' : 'No'}</dd>
              <dt>Shrink wrapped</dt><dd>{exception.shrink_wrapped ? 'Yes' : 'No'}</dd>
              <dt>Value range</dt>
              <dd>{VALUE_RANGES[exception.value_range]}{exception.dollar_amount ? ` ($${exception.dollar_amount})` : ''}</dd>
              <dt>Manufacturer / brand</dt><dd>{exception.manufacturer_brand || '—'}</dd>
              <dt>Additional details</dt><dd>{exception.additional_details || '—'}</dd>
              <dt>Content hash</dt><dd className="muted">{exception.content_hash.slice(0, 16)}…</dd>
              <dt>Created</dt><dd>{formatDate(exception.created_at)}</dd>
            </dl>
          </div>
        </div>

        <div>
          <div className="panel">
            <h2>Root cause classification</h2>
            {latest ? (
              <>
                <div className="row">
                  <strong style={{ fontSize: 16 }}>{latest.category}</strong>
                  <span className="badge">{(latest.confidence * 100).toFixed(0)}% confidence</span>
                  <SourceBadge source={latest.source} />
                  {latest.needs_review && <span className="badge review">Needs review</span>}
                </div>
                <details style={{ marginTop: 10 }}>
                  <summary>Why?</summary>
                  <p>{latest.reasoning || '—'}</p>
                  <p className="muted">
                    {latest.model_used} · {formatDate(latest.classified_at)}
                  </p>
                </details>
              </>
            ) : (
              <p className="muted">Not classified yet.</p>
            )}

            <div className="row" style={{ marginTop: 14 }}>
              <button
                onClick={() => run(() => classifyException(id), 'Classification complete.')}
                disabled={busy}
              >
                {latest ? 'Re-classify' : 'Classify'}
              </button>
            </div>

            <div className="row" style={{ marginTop: 14 }}>
              <div className="field">
                <label>Override category</label>
                <select value={override} onChange={(e) => setOverride(e.target.value)}>
                  <option value="">Select…</option>
                  {taxonomy.map((t) => (
                    <option key={t.category} value={t.category}>{t.category}</option>
                  ))}
                </select>
              </div>
              <button
                className="secondary"
                disabled={busy || !override || override === latest?.category}
                onClick={() =>
                  run(
                    () => overrideCategory(id, { category: override, reviewer: 'demo-user' }),
                    'Override saved as a new history entry.',
                  )
                }
              >
                Save override
              </button>
            </div>
          </div>

          <div className="panel">
            <h2>Clear exception</h2>
            {exception.cleared_at ? (
              <p>
                Cleared <strong>{exception.clearing_code}</strong> on {formatDate(exception.cleared_at)}
              </p>
            ) : (
              <p className="muted">Not cleared yet.</p>
            )}
            <div className="row">
              <div className="field">
                <label>Clearing code</label>
                <select value={clearingCode} onChange={(e) => setClearingCode(e.target.value)}>
                  <option value="">Select…</option>
                  {clearingCodes.map((c) => (
                    <option key={c.code} value={c.code}>{`${c.code} — ${c.full_form}`}</option>
                  ))}
                </select>
              </div>
              <button
                disabled={busy || !clearingCode}
                onClick={() =>
                  run(
                    () => clearException(id, { clearing_code: clearingCode, cleared_by: 'demo-user' }),
                    'Exception cleared.',
                  )
                }
              >
                Clear
              </button>
            </div>
          </div>

          <div className="panel">
            <h2>Classification history ({history.length})</h2>
            <table>
              <thead>
                <tr><th>When</th><th>Category</th><th>Conf.</th><th>Source</th></tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.id}>
                    <td>{formatDate(row.classified_at)}</td>
                    <td>{row.category}</td>
                    <td>{row.confidence.toFixed(2)}</td>
                    <td><SourceBadge source={row.source} /></td>
                  </tr>
                ))}
                {history.length === 0 && (
                  <tr><td colSpan={4} className="muted">No classification events yet.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
