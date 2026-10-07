import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  acknowledgeFlag,
  errorMessage,
  evaluateRecommendations,
  getAttentionFlags,
  getCommodities,
  getFilterOptions,
  getFlagEvidence,
  getRecommendationLineage,
  getTerminals,
  resolveFlag,
  scanAttention,
  watchCheck,
} from '../api/client.js';
import WatchPanel from '../components/WatchPanel.jsx';
import useDebounced from '../lib/useDebounced.js';
import { formatDate, formatDateOnly } from '../lib/format.js';

const STATUS_LABELS = {
  open: 'Needs attention',
  acknowledged: 'Owned',
  resolved: 'Closed',
};

const DEFAULT_SCAN = { window_days: 30, periods: 3, threshold: 3, min_consecutive: 2 };

const EMPTY_WATCH = { origin_terminal: '', destination_terminal: '', commodity_code: '' };

const VERDICTS = {
  effective: { label: 'Working', cls: 'cache' },
  escalated: { label: 'Escalated', cls: 'human' },
  ceiling_reached_flagged: { label: 'Escalated to training', cls: 'review' },
  ceiling_reached_no_terminal_scope: { label: 'Ceiling reached', cls: 'review' },
  ineffective_no_replacement: { label: 'Not working', cls: 'review' },
  insufficient_evidence: { label: 'Too early to tell', cls: '' },
};

function Sparkline({ counts, threshold }) {
  const max = Math.max(threshold, ...counts, 1);
  // Newest period first in the data; render oldest -> newest so it reads left to right.
  return (
    <div className="spark" title={`Newest period first: ${counts.join(', ')}`}>
      {[...counts].reverse().map((count, index) => (
        <span
          key={index}
          className={`spark-bar ${count >= threshold ? 'is-breach' : ''}`}
          style={{ height: `${Math.max(8, (count / max) * 100)}%` }}
        >
          <b>{count}</b>
        </span>
      ))}
    </div>
  );
}

export default function AttentionPage() {
  const [summary, setSummary] = useState({ open: 0, acknowledged: 0, resolved: 0, high_severity_active: 0 });
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState('');
  const [scopeFilter, setScopeFilter] = useState('');
  const [scan, setScan] = useState(DEFAULT_SCAN);
  const [evidence, setEvidence] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const [watchScope, setWatchScope] = useState(EMPTY_WATCH);
  const [watch, setWatch] = useState(null);
  const [watchLoading, setWatchLoading] = useState(false);
  const [terminals, setTerminals] = useState([]);
  const [commodities, setCommodities] = useState([]);

  const [effectiveness, setEffectiveness] = useState(null);
  const [lineage, setLineage] = useState({});

  useEffect(() => {
    Promise.all([getTerminals(), getCommodities(), getFilterOptions()])
      .then(([terms, comms, opts]) => {
        setTerminals([...new Set([...terms, ...(opts.terminals ?? [])])].sort());
        const known = new Set(comms.map((c) => c.code));
        const extra = (opts.commodity_codes ?? [])
          .filter((code) => !known.has(code))
          .map((code) => ({ code, description: '(not in master)' }));
        setCommodities([...comms, ...extra]);
      })
      .catch(() => {
        /* the watch lookup still works with the fields left blank */
      });
  }, []);

  // Lookup only — no model call, so it can follow the selectors directly.
  const watchKey = useDebounced(JSON.stringify(watchScope), 400);

  useEffect(() => {
    const scope = JSON.parse(watchKey);
    if (!scope.origin_terminal && !scope.commodity_code) {
      setWatch(null);
      return undefined;
    }
    const controller = new AbortController();
    setWatchLoading(true);
    watchCheck({ ...scope, days: 0 }, { signal: controller.signal })
      .then(setWatch)
      .catch((err) => {
        if (!controller.signal.aborted) setError(errorMessage(err));
      })
      .finally(() => setWatchLoading(false));
    return () => controller.abort();
  }, [watchKey]);

  const watchField = (key) => (event) =>
    setWatchScope((prev) => ({ ...prev, [key]: event.target.value }));

  const load = useCallback(async () => {
    setError('');
    try {
      const params = {};
      if (statusFilter) params.status = statusFilter;
      if (scopeFilter) params.scope_type = scopeFilter;
      const data = await getAttentionFlags(params);
      setSummary(data.summary);
      setItems(data.items);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [statusFilter, scopeFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const run = async (action, message) => {
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const result = await action();
      await load();
      setNotice(typeof message === 'function' ? message(result) : message);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const runScan = () =>
    run(
      () => scanAttention({ ...scan, window_days: Number(scan.window_days), periods: Number(scan.periods), threshold: Number(scan.threshold), min_consecutive: Number(scan.min_consecutive) }),
      (result) =>
        result.created + result.updated + result.cleared === 0
          ? 'Scan complete — no terminal or handler crossed the repeat-issue threshold. Nothing to action.'
          : `Scan complete — ${result.created} new, ${result.updated} still breaching, ${result.cleared} cleared.`,
    );

  const showEvidence = async (flag) => {
    setError('');
    try {
      setEvidence(await getFlagEvidence(flag.id));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  // Tier 3 close-the-loop: did the recommendations actually reduce recurrence?
  const runEffectiveness = () =>
    run(
      async () => {
        const data = await evaluateRecommendations({ window_days: 30 });
        setEffectiveness(data);
        // Only escalated chains have a lineage worth showing.
        const chains = await Promise.all(
          data.results
            .filter((r) => r.escalation_level > 0 || r.verdict === 'escalated')
            .map((r) =>
              getRecommendationLineage(r.recommendation_id)
                .then((l) => [r.recommendation_id, l])
                .catch(() => null),
            ),
        );
        setLineage(Object.fromEntries(chains.filter(Boolean)));
        return data;
      },
      (data) =>
        data.considered === 0
          ? 'No recommendation is old enough to judge yet — they need a full window behind them.'
          : `Reviewed ${data.considered} recommendation(s) — ${data.effective} working, ${data.escalated} escalated, ${data.attention_flags_raised} raised for training.`,
    );

  const scanField = (key, label, min, max) => (
    <label className="field">
      <span>{label}</span>
      <input
        type="number"
        min={min}
        max={max}
        value={scan[key]}
        onChange={(e) => setScan((prev) => ({ ...prev, [key]: e.target.value }))}
      />
    </label>
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Attention &amp; training</h1>
          <p className="subtitle">
            Where the repeat root causes are, and what to do about them before the next overage.
            Flags are raised only when the same cause breaches the threshold in consecutive
            periods — addressed to a supervisor, not buried in a dashboard.
          </p>
        </div>
      </div>

      <div className="panel watch-panel">
        <div className="panel-head">
          <h2>What to watch</h2>
          <span className="panel-hint">
            Read before the freight is handled — a lookup, no AI call
          </span>
        </div>
        <div className="watch-grid">
          <div className="watch-scope">
            <label className="field">
              <span>Terminal</span>
              <select value={watchScope.origin_terminal} onChange={watchField('origin_terminal')}>
                <option value="">Select…</option>
                {terminals.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Outbound lane to</span>
              <select
                value={watchScope.destination_terminal}
                onChange={watchField('destination_terminal')}
              >
                <option value="">Any destination</option>
                {terminals.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Commodity</span>
              <select value={watchScope.commodity_code} onChange={watchField('commodity_code')}>
                <option value="">Any commodity</option>
                {commodities.map((c) => (
                  <option key={c.code} value={c.code}>
                    {c.code} — {c.description}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted watch-note">
              This is the prevention side: it runs on freight that is still moving, so the overage
              never has to be logged in the first place.
            </p>
          </div>
          <WatchPanel result={watch} loading={watchLoading} />
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Are the prevention actions working?</h2>
          <button type="button" className="secondary" onClick={runEffectiveness} disabled={busy}>
            {busy ? 'Checking…' : 'Check effectiveness'}
          </button>
        </div>
        <p className="muted watch-note">
          Compares recurrence in the 30 days before and after each recommendation. One that did not
          move the number is replaced with a sharper one; once a pattern has been escalated twice,
          more wording is not the answer and it is raised as a training flag instead.
        </p>

        {effectiveness && effectiveness.results.length === 0 && (
          <p className="empty">
            Nothing to judge yet — recommendations need a full window behind them before the
            before/after comparison means anything.
          </p>
        )}

        {effectiveness?.results.map((item) => {
          const verdict = VERDICTS[item.verdict] ?? { label: item.verdict, cls: '' };
          const chain = lineage[item.recommendation_id];
          return (
            <div className="rec" key={item.recommendation_id}>
              <div className="row">
                <span className={`badge ${verdict.cls}`}>{verdict.label}</span>
                <span className="badge">{item.category}</span>
                {item.scope?.terminal && <span className="badge">{item.scope.terminal}</span>}
                <span className="spacer" />
                <span className="muted" style={{ fontSize: 11 }}>
                  {item.before} → {item.after} exceptions ·{' '}
                  {Math.round(item.improvement * 100)}% change
                </span>
              </div>

              {chain && (
                <p className="rec-pattern">
                  <span className="badge human">Attempt {chain.position} of {chain.length}</span>{' '}
                  {chain.escalated
                    ? 'escalated from an earlier recommendation that did not reduce recurrence.'
                    : 'first attempt at this pattern.'}
                </p>
              )}

              {item.verdict === 'escalated' && (
                <p className="rec-pattern">
                  Replaced with a sharper recommendation (escalation level{' '}
                  {item.new_escalation_level}).
                </p>
              )}
              {item.verdict === 'ceiling_reached_flagged' && (
                <p className="flag-action">
                  <span>Escalation ceiling reached</span>
                  Raised as an attention flag for {item.scope?.terminal} — see the list below.
                </p>
              )}
              {item.checks?.resolved_checks > 0 && (
                <div className="rec-pattern">
                  Staging checks on this scope: {item.checks.prevented} prevented,{' '}
                  {item.checks.recurred} recurred.
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="kpi-row">
        <div className="kpi">
          <span className="kpi-label">Needs attention</span>
          <span className="kpi-value">{summary.open}</span>
          <span className="kpi-note">Unowned repeat patterns</span>
        </div>
        <div className="kpi accent-blue">
          <span className="kpi-label">Owned</span>
          <span className="kpi-value">{summary.acknowledged}</span>
          <span className="kpi-note">Acknowledged by a supervisor</span>
        </div>
        <div className="kpi accent-green">
          <span className="kpi-label">Closed</span>
          <span className="kpi-value">{summary.resolved}</span>
          <span className="kpi-note">Resolved or no longer breaching</span>
        </div>
        <div className="kpi accent-amber">
          <span className="kpi-label">High severity</span>
          <span className="kpi-value">{summary.high_severity_active}</span>
          <span className="kpi-note">Three periods or double the threshold</span>
        </div>
      </div>

      <div className="panel filters toolbar">
        <label className="field">
          <span>Status</span>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">All</option>
            <option value="open">Needs attention</option>
            <option value="acknowledged">Owned</option>
            <option value="resolved">Closed</option>
          </select>
        </label>
        <label className="field">
          <span>Scope</span>
          <select value={scopeFilter} onChange={(e) => setScopeFilter(e.target.value)}>
            <option value="">Terminals &amp; handlers</option>
            <option value="terminal">Terminals</option>
            <option value="handler">Handlers</option>
          </select>
        </label>
        <span className="spacer" />
        {scanField('window_days', 'Period (days)', 1, 365)}
        {scanField('periods', 'Periods', 2, 12)}
        {scanField('threshold', 'Threshold', 1, 100)}
        <button type="button" onClick={runScan} disabled={busy}>
          {busy ? 'Scanning…' : 'Scan for repeat issues'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {notice && <p className="notice-good">{notice}</p>}

      {items.length === 0 ? (
        <div className="panel">
          <p className="empty">
            No flags. Either nothing is repeating, or the classified history does not cover enough
            periods yet — run a scan to check.
          </p>
        </div>
      ) : (
        <div className="flag-list">
          {items.map((flag) => (
            <div className={`panel flag flag-${flag.status} sev-${flag.severity}`} key={flag.id}>
              <div className="flag-head">
                <div>
                  <span className="flag-scope">
                    {flag.scope_type === 'terminal' ? 'Terminal' : 'Handler'} {flag.scope_value}
                  </span>
                  <h2>{flag.category}</h2>
                </div>
                <div className="row">
                  <span className={`badge ${flag.severity === 'high' ? 'review' : 'human'}`}>
                    {flag.severity === 'high' ? 'High severity' : 'Watch'}
                  </span>
                  <span className={`badge ${flag.status === 'resolved' ? 'cache' : ''}`}>
                    {STATUS_LABELS[flag.status]}
                  </span>
                </div>
              </div>

              <div className="flag-body">
                <Sparkline counts={flag.period_counts} threshold={flag.threshold} />
                <div className="flag-text">
                  <p>{flag.pattern_summary}</p>
                  <p className="flag-action">
                    <span>Suggested action</span>
                    {flag.suggested_action}
                  </p>
                </div>
              </div>

              <div className="row flag-foot">
                <span className="muted">
                  {flag.consecutive_periods} consecutive period(s) · {flag.total_count} exceptions ·
                  last seen {formatDateOnly(flag.last_detected_at)}
                </span>
                <span className="spacer" />
                <button type="button" className="secondary" onClick={() => showEvidence(flag)}>
                  {flag.supporting_exception_ids.length} supporting exceptions
                </button>
                {flag.status === 'open' && (
                  <button
                    type="button"
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      run(
                        () => acknowledgeFlag(flag.id, { actor: 'supervisor' }),
                        (r) => r.confirmation,
                      )
                    }
                  >
                    Acknowledge
                  </button>
                )}
                {flag.status !== 'resolved' && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() =>
                      run(
                        () =>
                          resolveFlag(flag.id, {
                            actor: 'supervisor',
                            note: 'Training refresh delivered.',
                          }),
                        (r) => r.confirmation,
                      )
                    }
                  >
                    Mark actioned
                  </button>
                )}
              </div>

              {flag.status === 'resolved' && (
                <p className="flag-resolved">
                  ✓ {flag.resolution_note || 'Closed out.'}{' '}
                  {flag.resolved_at ? `· ${formatDate(flag.resolved_at)}` : ''}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {evidence && (
        <div className="panel">
          <div className="panel-head">
            <h2>
              Supporting exceptions — {evidence.scope_value} · {evidence.category}
            </h2>
            <button type="button" className="secondary" onClick={() => setEvidence(null)}>
              Close
            </button>
          </div>
          <table>
            <thead>
              <tr>
                <th>PRO</th>
                <th>Origin</th>
                <th>Dest</th>
                <th>Commodity</th>
                <th>Entry user</th>
                <th>Logged</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {evidence.exceptions.map((row) => (
                <tr key={row.id}>
                  <td>
                    <Link to={`/exceptions/${row.id}`}>{row.pro_number}</Link>
                  </td>
                  <td>{row.origin_terminal}</td>
                  <td>{row.destination_terminal}</td>
                  <td>{row.commodity_code}</td>
                  <td>{row.entry_user}</td>
                  <td>{formatDateOnly(row.created_at)}</td>
                  <td>{row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
