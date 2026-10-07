import { useEffect, useState } from 'react';
import {
  confirmQuantityCheck,
  correctQuantityCheck,
  errorMessage,
  getTerminals,
  quantityVerify,
} from '../api/client.js';
import { formatDate } from '../lib/format.js';

const EMPTY = { pro_number: '', terminal: '', scanned_quantity: '', actor: 'dock' };

const RESULT_LABELS = {
  match: 'Counts agree',
  mismatch_pending: 'Discrepancy — needs a follow-up',
  mismatch_corrected: 'Recount filed',
  mismatch_confirmed: 'Discrepancy confirmed',
};

function RiskBrief({ risk }) {
  if (!risk) return null;
  const cls = risk.elevated_attention ? risk.risk_level : 'clear';
  return (
    <div className={`guard guard-${cls}`}>
      <div className="guard-head">
        <span className="guard-title">
          {risk.elevated_attention ? 'Elevated attention on this scope' : 'Nothing concentrated here'}
        </span>
      </div>
      <p className="guard-body">{risk.message}</p>
      {risk.signals.map((signal) => (
        <div className="guard-signal" key={signal.category}>
          <div className="guard-signal-head">
            <strong>{signal.category}</strong>
            <span className={`badge ${signal.severity === 'high' ? 'review' : 'human'}`}>
              {signal.severity}
            </span>
          </div>
          <p className="guard-pattern">{signal.pattern}</p>
        </div>
      ))}
    </div>
  );
}

/**
 * Tier 2 — the prevention form. Verified on the dock while the freight is still staged,
 * so a miscount is caught before it becomes an overage. Never on the exception log form.
 */
export default function StagingCheckPage() {
  const [form, setForm] = useState(EMPTY);
  const [terminals, setTerminals] = useState([]);
  const [result, setResult] = useState(null);
  const [correction, setCorrection] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    getTerminals()
      .then(setTerminals)
      .catch(() => {
        /* the terminal can still be typed if the master list is unavailable */
      });
  }, []);

  const update = (key) => (event) =>
    setForm((prev) => ({ ...prev, [key]: event.target.value }));

  const check = result?.check ?? null;
  const pending = check?.verification_result === 'mismatch_pending';

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError('');
    setNotice('');
    setCorrection('');
    setReason('');
    try {
      const data = await quantityVerify({
        pro_number: form.pro_number.trim(),
        terminal: form.terminal.trim().toUpperCase(),
        scanned_quantity: Number(form.scanned_quantity),
        actor: form.actor.trim() || 'dock',
      });
      setResult(data);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const followUp = async (action, message) => {
    setBusy(true);
    setError('');
    try {
      const updated = await action();
      setResult((prev) => ({ ...prev, check: updated, requires_followup: [] }));
      setNotice(message);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Staging check</h1>
          <p className="subtitle">
            Count and BOL verification while the freight is still on the dock. If the piece count
            does not match what is expected, the discrepancy is resolved here — before anyone has
            to log an overage.
          </p>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Verify quantity against the expected shipment</h2>
          <span className="panel-hint">A lookup and a recorded check — no AI call</span>
        </div>
        <form className="toolbar" onSubmit={submit}>
          <label className="field">
            <span>PRO number</span>
            <input
              value={form.pro_number}
              onChange={update('pro_number')}
              placeholder="402118834007"
              required
            />
          </label>
          <label className="field">
            <span>Terminal</span>
            <select value={form.terminal} onChange={update('terminal')} required>
              <option value="">Select…</option>
              {terminals.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>Pieces scanned</span>
            <input
              type="number"
              min="0"
              value={form.scanned_quantity}
              onChange={update('scanned_quantity')}
              required
            />
          </label>
          <label className="field">
            <span>Checked by</span>
            <input value={form.actor} onChange={update('actor')} />
          </label>
          <span className="spacer" />
          <button type="submit" disabled={busy}>
            {busy ? 'Checking…' : 'Verify count'}
          </button>
        </form>
        <p className="muted watch-note">
          Expected counts come from a POC reference table that stands in for the real manifest /
          OD400 lookup.
        </p>
      </div>

      {error && <p className="error">{error}</p>}
      {notice && <p className="notice-good">{notice}</p>}

      {result && (
        <div className="panel">
          <div className="panel-head">
            <h2>
              PRO {result.pro_number}
              {check && (
                <span className={`badge ${check.verification_result === 'match' ? 'cache' : 'review'}`} style={{ marginLeft: 10 }}>
                  {RESULT_LABELS[check.verification_result]}
                </span>
              )}
            </h2>
            <button type="button" className="secondary" onClick={() => setResult(null)}>
              Clear
            </button>
          </div>

          <p>{result.message}</p>

          {check && (
            <div className="chip-row" style={{ marginTop: 10 }}>
              <span className="chip"><span>Expected</span><b>{check.expected_quantity}</b></span>
              <span className="chip"><span>Scanned</span><b>{check.scanned_quantity}</b></span>
              {check.corrected_quantity != null && (
                <span className="chip"><span>Recounted</span><b>{check.corrected_quantity}</b></span>
              )}
              <span className="chip"><span>Terminal</span><b>{check.terminal}</b></span>
              <span className="chip"><span>Checked</span><b>{formatDate(check.performed_at)}</b></span>
            </div>
          )}

          <div style={{ marginTop: 14 }}>
            <RiskBrief risk={result.risk} />
          </div>

          {pending && (
            <div className="dash-grid" style={{ marginTop: 14 }}>
              <div className="rec">
                <b>Recount and correct</b>
                <p className="rec-pattern">
                  The count was wrong, not the freight — file the true piece count.
                </p>
                <div className="toolbar" style={{ marginTop: 8 }}>
                  <label className="field">
                    <span>Corrected pieces</span>
                    <input
                      type="number"
                      min="0"
                      value={correction}
                      onChange={(e) => setCorrection(e.target.value)}
                    />
                  </label>
                  <button
                    type="button"
                    disabled={busy || correction === ''}
                    onClick={() =>
                      followUp(
                        () =>
                          correctQuantityCheck(check.id, {
                            corrected_quantity: Number(correction),
                            actor: form.actor.trim() || 'dock',
                          }),
                        'Recount filed — the staged count now matches the manifest.',
                      )
                    }
                  >
                    File recount
                  </button>
                </div>
              </div>

              <div className="rec">
                <b>Confirm the discrepancy</b>
                <p className="rec-pattern">
                  The count is right and the shipment genuinely differs — say why, so the cause is
                  on record before it turns into an exception.
                </p>
                <div className="toolbar" style={{ marginTop: 8 }}>
                  <label className="field" style={{ flex: 1 }}>
                    <span>Reason</span>
                    <input
                      value={reason}
                      onChange={(e) => setReason(e.target.value)}
                      placeholder="Shipper over-shipped; consignee will accept the extra pieces."
                    />
                  </label>
                  <button
                    type="button"
                    disabled={busy || reason.trim().length < 3}
                    onClick={() =>
                      followUp(
                        () =>
                          confirmQuantityCheck(check.id, {
                            reason: reason.trim(),
                            actor: form.actor.trim() || 'dock',
                          }),
                        'Discrepancy confirmed and recorded against this PRO.',
                      )
                    }
                  >
                    Confirm discrepancy
                  </button>
                </div>
              </div>
            </div>
          )}

          {check && !pending && check.action_taken && (
            <p className="flag-resolved">✓ {check.action_taken}</p>
          )}
        </div>
      )}
    </>
  );
}
