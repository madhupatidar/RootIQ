import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import {
  errorMessage,
  generateRecommendations,
  getAccuracy,
  getCacheStats,
  getCommodities,
  getDistribution,
  getFilterOptions,
  getRecommendationEvidence,
  getRecommendations,
  getTerminals,
} from '../api/client.js';
import { formatDate } from '../lib/format.js';

const BAR_COLORS = [
  '#b0112a', '#1f5fa8', '#12855f', '#b26a00', '#6b4ea8', '#0f7c8c',
  '#d4553f', '#4a7fc1', '#3f9e78', '#a8497c', '#8a8f3c', '#66748a',
];

const WINDOWS = [
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
  { value: 365, label: 'Last 365 days' },
  { value: 0, label: 'All time' },
];

/** The multi-factor signals the classifier reports alongside the category. */
const FACTOR_LABELS = {
  terminal_pattern: 'Recurring at this terminal',
  handler_pattern: 'Same handler repeating',
  scan_issue: 'Scan issue',
  quantity_mismatch: 'Quantity mismatch',
  trailer_bay_mismatch: 'Trailer / bay mismatch',
  documentation_issue: 'Documentation issue',
  training_signal: 'Training signal',
};

const FACTOR_TONE = {
  terminal_pattern: 'review',
  handler_pattern: 'review',
  training_signal: 'human',
};

function FactorBadges({ factors, showCount = true }) {
  if (!factors || factors.length === 0) return <span className="muted">—</span>;
  return (
    <span className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
      {factors.map((f) => (
        <span className={`badge ${FACTOR_TONE[f.factor] ?? 'fresh'}`} key={f.factor}>
          {FACTOR_LABELS[f.factor] ?? f.factor}
          {showCount ? ` · ${f.count}` : ''}
        </span>
      ))}
    </span>
  );
}

/** Collapse a [{ <key>, category, count }] breakdown into a ranked list per key value. */
function rollup(rows, key) {
  const map = new Map();
  for (const row of rows ?? []) {
    const name = row[key] || 'Unknown';
    const entry = map.get(name) ?? { name, count: 0, leadCategory: null, leadCount: 0 };
    entry.count += row.count;
    if (row.count > entry.leadCount) {
      entry.leadCount = row.count;
      entry.leadCategory = row.category;
    }
    map.set(name, entry);
  }
  return [...map.values()].sort((a, b) => b.count - a.count);
}

function RankList({ items, total, emptyText, describe }) {
  if (items.length === 0) return <p className="empty">{emptyText}</p>;
  const max = items[0].count || 1;
  return (
    <div className="rank-list">
      {items.map((item) => (
        <div className="rank-item" key={item.name}>
          <div className="rank-top">
            <span className="rank-name">{item.name}</span>
            <span className="rank-count">
              {item.count} · {total ? Math.round((item.count / total) * 100) : 0}%
            </span>
          </div>
          <span className="rank-track">
            <span className="rank-fill" style={{ width: `${(item.count / max) * 100}%` }} />
          </span>
          <span className="rank-sub">{describe(item)}</span>
        </div>
      ))}
    </div>
  );
}

export default function DashboardPage() {
  const [scope, setScope] = useState({ terminal: '', commodity_code: '', days: 90 });
  const [options, setOptions] = useState({ terminals: [], commodity_codes: [] });
  const [commodities, setCommodities] = useState([]);
  const [terminals, setTerminals] = useState([]);
  const [distribution, setDistribution] = useState({ total_classified: 0, categories: [] });
  const [breakdowns, setBreakdowns] = useState(null);
  const [cacheStats, setCacheStats] = useState(null);
  const [accuracy, setAccuracy] = useState(null);
  const [recommendations, setRecommendations] = useState([]);
  const [evidence, setEvidence] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const params = { days: scope.days, include_breakdowns: true };
      if (scope.terminal) params.terminal = scope.terminal;
      if (scope.commodity_code) params.commodity_code = scope.commodity_code;
      const [dist, stats, acc, recs] = await Promise.all([
        getDistribution(params),
        getCacheStats(),
        getAccuracy(),
        getRecommendations(),
      ]);
      setDistribution(dist);
      setBreakdowns(dist.breakdowns ?? null);
      setCacheStats(stats);
      setAccuracy(acc);
      setRecommendations(recs);
    } catch (err) {
      setError(errorMessage(err));
    }
  }, [scope]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    Promise.all([getFilterOptions(), getCommodities(), getTerminals()])
      .then(([opts, comms, terms]) => {
        setOptions(opts);
        setCommodities(comms);
        setTerminals(terms);
      })
      .catch((err) => setError(errorMessage(err)));
  }, []);

  // Official master first, plus anything present in the data that is not in the master,
  // so records from retired or non-standard terminals stay filterable.
  const terminalOptions = useMemo(
    () => [...new Set([...terminals, ...options.terminals])].sort(),
    [terminals, options.terminals],
  );

  const commodityOptions = useMemo(() => {
    const known = new Set(commodities.map((c) => c.code));
    const extra = options.commodity_codes
      .filter((code) => !known.has(code))
      .map((code) => ({ code, description: '(not in master)' }));
    return [...commodities, ...extra];
  }, [commodities, options.commodity_codes]);

  const commodityLabel = useMemo(() => {
    const map = new Map(commodityOptions.map((c) => [c.code, c.description]));
    return (code) => (map.get(code) ? `${code} — ${map.get(code)}` : code);
  }, [commodityOptions]);

  const total = distribution.total_classified;
  const categories = distribution.categories;
  const leader = categories[0] ?? null;
  const factors = distribution.factors ?? [];

  const avgConfidence = useMemo(() => {
    if (!total) return null;
    const weighted = categories.reduce((sum, c) => sum + (c.avg_confidence ?? 0) * c.count, 0);
    return weighted / total;
  }, [categories, total]);

  const lowConfidence = useMemo(
    () => categories.filter((c) => (c.avg_confidence ?? 0) < 0.6).reduce((sum, c) => sum + c.count, 0),
    [categories],
  );

  const topTerminals = useMemo(
    () => rollup(breakdowns?.by_origin_terminal, 'origin_terminal').slice(0, 6),
    [breakdowns],
  );

  const topCommodities = useMemo(
    () => rollup(breakdowns?.by_commodity, 'commodity_code').slice(0, 6),
    [breakdowns],
  );

  const windowLabel =
    WINDOWS.find((w) => String(w.value) === String(scope.days))?.label ?? '—';

  const regenerate = async () => {
    setBusy(true);
    setError('');
    try {
      await generateRecommendations({
        terminal: scope.terminal || null,
        commodity_code: scope.commodity_code || null,
        days: Number(scope.days),
      });
      await load();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const showEvidence = async (rec) => {
    try {
      setEvidence(await getRecommendationEvidence(rec.id));
    } catch (err) {
      setError(errorMessage(err));
    }
  };

  const update = (key) => (event) =>
    setScope((prev) => ({ ...prev, [key]: event.target.value }));

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Root Cause Dashboard</h1>
          <p className="subtitle">
            Why overage freight turns up, where it concentrates, and what to fix first.
          </p>
        </div>
        <div className="chip-row">
          <span className="chip"><span>Window</span><b>{windowLabel}</b></span>
          <span className="chip"><span>Terminal</span><b>{scope.terminal || 'All'}</b></span>
          <span className="chip"><span>Commodity</span><b>{scope.commodity_code || 'All'}</b></span>
        </div>
      </div>

      <div className="toolbar">
        <div className="field">
          <label>Terminal</label>
          <select value={scope.terminal} onChange={update('terminal')}>
            <option value="">All terminals</option>
            {terminalOptions.map((t) => (<option key={t} value={t}>{t}</option>))}
          </select>
        </div>
        <div className="field">
          <label>Commodity</label>
          <select value={scope.commodity_code} onChange={update('commodity_code')}>
            <option value="">All commodities</option>
            {commodityOptions.map((c) => (
              <option key={c.code} value={c.code}>{`${c.code} — ${c.description}`}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Time window</label>
          <select value={scope.days} onChange={update('days')}>
            {WINDOWS.map((w) => (<option key={w.value} value={w.value}>{w.label}</option>))}
          </select>
        </div>
        <div className="spacer" />
        <button
          onClick={regenerate}
          disabled={busy}
          title="Asks the AI to re-read the analyzed exceptions in this scope and rewrite the prevention actions"
        >
          {busy ? 'Generating prevention actions…' : 'Regenerate prevention actions'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="kpi-row">
        <div className="kpi">
          <span className="kpi-label">Exceptions analyzed</span>
          <span className="kpi-value">{total.toLocaleString()}</span>
          <span className="kpi-note">Root cause identified · {windowLabel.toLowerCase()}</span>
        </div>
        <div className="kpi accent-blue">
          <span className="kpi-label">Leading root cause</span>
          <span className="kpi-value is-text">{leader ? leader.category : '—'}</span>
          <span className="kpi-note">
            {leader
              ? `${leader.count} exceptions · ${leader.percentage}% of scope`
              : 'Nothing analyzed yet'}
          </span>
        </div>
        <div className="kpi accent-green">
          <span className="kpi-label">Average AI confidence</span>
          <span className="kpi-value">{avgConfidence != null ? avgConfidence.toFixed(2) : '—'}</span>
          <span className="kpi-note">
            {lowConfidence > 0
              ? `${lowConfidence} sit in low-confidence causes — worth a human read`
              : 'No low-confidence causes in this scope'}
          </span>
        </div>
        <div className="kpi accent-amber">
          <span className="kpi-label">Distinct causes</span>
          <span className="kpi-value">{categories.length}</span>
          <span className="kpi-note">
            {total
              ? `Top 3 cover ${Math.round(
                  (categories.slice(0, 3).reduce((s, c) => s + c.count, 0) / total) * 100,
                )}% of the scope`
              : 'Nothing analyzed yet'}
          </span>
        </div>
      </div>

      <div className="meta-strip">
        <span>
          Reuse cache: <b>{cacheStats ? `${(cacheStats.cache_hit_rate * 100).toFixed(0)}%` : '—'}</b>{' '}
          hit rate, <b>{cacheStats?.ollama_calls_saved ?? 0}</b> AI calls avoided
        </span>
        <span>Unique note fingerprints: <b>{cacheStats?.unique_content_hashes ?? '—'}</b></span>
        <span>
          Benchmark accuracy:{' '}
          <b>{accuracy && accuracy.evaluated ? `${(accuracy.accuracy * 100).toFixed(0)}%` : '—'}</b>{' '}
          on <b>{accuracy?.evaluated ?? 0}</b> hand-labeled cases
        </span>
      </div>

      <div className="dash-grid">
        <div className="panel">
          <div className="panel-head">
            <h2>Root cause mix</h2>
            <span className="panel-hint">Share of analyzed exceptions in scope</span>
          </div>
          {categories.length === 0 ? (
            <p className="empty">
              Nothing analyzed in this scope yet — widen the time window, or run the AI from the
              OV Exceptions page.
            </p>
          ) : (
            <>
              {factors.length > 0 && (
                <div style={{ marginBottom: 12 }}>
                  <span className="panel-hint">
                    What is driving them — contributing factors across this scope
                  </span>
                  <div style={{ marginTop: 6 }}>
                    <FactorBadges factors={factors} />
                  </div>
                </div>
              )}
              <ResponsiveContainer width="100%" height={Math.max(280, categories.length * 36)}>
                <BarChart
                  data={categories}
                  layout="vertical"
                  margin={{ left: 8, right: 28, top: 4, bottom: 4 }}
                >
                  <CartesianGrid horizontal={false} stroke="rgba(22, 32, 46, .12)" />
                  <XAxis type="number" stroke="#4d5c72" allowDecimals={false} tickLine={false} />
                  <YAxis
                    type="category"
                    dataKey="category"
                    width={200}
                    stroke="#4d5c72"
                    tickLine={false}
                    axisLine={false}
                    tick={{ fontSize: 11.5 }}
                  />
                  <Tooltip
                    cursor={{ fill: 'rgba(176, 17, 42, .07)' }}
                    contentStyle={{
                      background: 'rgba(255, 255, 255, .94)',
                      backdropFilter: 'blur(12px)',
                      border: '1px solid rgba(255, 255, 255, .8)',
                      borderRadius: 10,
                      boxShadow: '0 8px 24px rgba(22, 32, 46, .18)',
                      color: '#16202e',
                    }}
                    labelFormatter={() => ''}
                    formatter={(value, _name, entry) => [
                      `${value} exceptions · ${entry.payload.percentage}% · avg confidence ${entry.payload.avg_confidence}`,
                      entry.payload.category,
                    ]}
                  />
                  <Bar dataKey="count" radius={[0, 6, 6, 0]} barSize={18}>
                    {categories.map((entry, index) => (
                      <Cell key={entry.category} fill={BAR_COLORS[index % BAR_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>

              <details style={{ marginTop: 10 }}>
                <summary>Show the numbers behind this chart</summary>
                <table style={{ marginTop: 10 }}>
                  <thead>
                    <tr>
                      <th>Root cause</th>
                      <th className="right">Exceptions</th>
                      <th className="right">Share</th>
                      <th className="right">Avg confidence</th>
                      <th>Contributing factors</th>
                    </tr>
                  </thead>
                  <tbody>
                    {categories.map((c) => (
                      <tr key={c.category}>
                        <td>{c.category}</td>
                        <td className="right">{c.count}</td>
                        <td className="right">{c.percentage}%</td>
                        <td className="right">{c.avg_confidence}</td>
                        <td><FactorBadges factors={c.factors} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            </>
          )}
        </div>

        <div className="dash-col">
          <div className="panel">
            <div className="panel-head">
              <h2>Where overages originate</h2>
              <span className="panel-hint">Top origin terminals</span>
            </div>
            <RankList
              items={topTerminals}
              total={total}
              emptyText="No origin terminal data in this scope."
              describe={(item) => `Mostly: ${item.leadCategory ?? 'Unknown'}`}
            />
          </div>

          <div className="panel">
            <div className="panel-head">
              <h2>Freight most affected</h2>
              <span className="panel-hint">Top commodities</span>
            </div>
            <RankList
              items={topCommodities}
              total={total}
              emptyText="No commodity data in this scope."
              describe={(item) => commodityLabel(item.name)}
            />
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Prevention actions</h2>
          <span className="panel-hint">
            AI-drafted fixes for the patterns above — review before acting
          </span>
        </div>
        {recommendations.length === 0 ? (
          <p className="empty">
            None generated yet — analyze some exceptions, then use “Regenerate prevention actions”.
          </p>
        ) : (
          recommendations.map((rec) => (
            <div className="rec" key={rec.id}>
              <div className="row">
                <span className="badge">{rec.category}</span>
                <span className="muted" style={{ fontSize: 11 }}>{formatDate(rec.generated_at)}</span>
              </div>
              <p style={{ margin: '8px 0 0' }}>{rec.recommendation_text}</p>
              {rec.pattern_addressed && (
                <div className="rec-pattern">Pattern: {rec.pattern_addressed}</div>
              )}
              <button
                className="secondary"
                style={{ marginTop: 8 }}
                onClick={() => showEvidence(rec)}
              >
                View {rec.supporting_exception_ids.length} supporting exception(s)
              </button>
            </div>
          ))
        )}
      </div>

      {evidence && (
        <div className="panel">
          <div className="panel-head">
            <h2>Supporting exceptions · {evidence.category}</h2>
            <button className="secondary" onClick={() => setEvidence(null)}>Close</button>
          </div>
          <table>
            <thead>
              <tr><th>PRO</th><th>Origin</th><th>Dest</th><th>Commodity</th><th>Status</th><th>Clearing</th></tr>
            </thead>
            <tbody>
              {evidence.exceptions.map((e) => (
                <tr key={e.id}>
                  <td><Link to={`/exceptions/${e.id}`}>{e.pro_number}</Link></td>
                  <td>{e.origin_terminal}</td>
                  <td>{e.destination_terminal}</td>
                  <td>{commodityLabel(e.commodity_code)}</td>
                  <td>{e.status}</td>
                  <td>{e.clearing_code || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
