import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  classifyBatch,
  errorMessage,
  getClearingCodes,
  getCommodities,
  getFilterOptions,
  getTaxonomy,
  getTerminals,
  listExceptions,
} from '../api/client.js';
import SourceBadge from '../components/SourceBadge.jsx';
import { STATUS_LABELS, VALUE_RANGES, formatDateOnly } from '../lib/format.js';

const EMPTY_FILTERS = {
  terminal: '',
  commodity_code: '',
  value_range: '',
  status: '',
  clearing_code: '',
  category: '',
  date_from: '',
  date_to: '',
};

const PAGE_SIZES = [25, 50, 100, 250];

export default function ExceptionsPage() {
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(PAGE_SIZES[0]);
  const [data, setData] = useState({ total: 0, items: [] });
  const [options, setOptions] = useState({ terminals: [], commodity_codes: [] });
  const [commodities, setCommodities] = useState([]);
  const [terminals, setTerminals] = useState([]);
  const [clearingCodes, setClearingCodes] = useState([]);
  const [taxonomy, setTaxonomy] = useState([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // One source of truth for the query string, so the list and the batch classify call
  // always operate on exactly the same set of exceptions.
  const activeFilters = useCallback(() => {
    const params = Object.fromEntries(
      Object.entries(filters).filter(([, v]) => v !== '' && v !== null),
    );
    if (params.date_from) params.date_from = `${params.date_from}T00:00:00`;
    if (params.date_to) params.date_to = `${params.date_to}T23:59:59`;
    return params;
  }, [filters]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = activeFilters();
      params.limit = pageSize;
      params.offset = page * pageSize;
      setData(await listExceptions(params));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [activeFilters, page, pageSize]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    Promise.all([
      getFilterOptions(),
      getClearingCodes(),
      getTaxonomy(),
      getCommodities(),
      getTerminals(),
    ])
      .then(([opts, codes, tax, comms, terms]) => {
        setOptions(opts);
        setClearingCodes(codes);
        setTaxonomy(tax);
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
    return (row) => row.commodity_description || map.get(row.commodity_code) || row.commodity_code;
  }, [commodityOptions]);

  const update = (key) => (event) => {
    setPage(0);
    setFilters((prev) => ({ ...prev, [key]: event.target.value }));
  };

  const resetFilters = () => {
    setPage(0);
    setFilters(EMPTY_FILTERS);
  };

  const pageCount = Math.max(1, Math.ceil(data.total / pageSize));
  const firstRow = data.total === 0 ? 0 : page * pageSize + 1;
  const lastRow = page * pageSize + data.items.length;
  const filtered = Object.keys(activeFilters()).length > 0;

  const runBatch = async () => {
    setBusy(true);
    setError('');
    try {
      const result = await classifyBatch(activeFilters());
      await load();
      setError(
        result.processed === 0
          ? `Nothing left to analyze${filtered ? ' in the current filter' : ''} — every matching exception with investigation notes already has a root cause.`
          : `Analyzed ${result.processed}${filtered ? ' from the current filter' : ''}: ${result.ai_fresh} fresh AI calls, ${result.cache_hits} cache hits, ${result.needs_review} flagged for review.`,
      );
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h1>OV Exceptions</h1>
      <p className="subtitle">Overage exceptions only — {data.total} matching record(s).</p>

      <div className="panel filters">
        <div className="field">
          <label>Terminal</label>
          <select value={filters.terminal} onChange={update('terminal')}>
            <option value="">All</option>
            {terminalOptions.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Commodity</label>
          <select value={filters.commodity_code} onChange={update('commodity_code')}>
            <option value="">All</option>
            {commodityOptions.map((c) => (
              <option key={c.code} value={c.code}>{`${c.code} — ${c.description}`}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Value range</label>
          <select value={filters.value_range} onChange={update('value_range')}>
            <option value="">All</option>
            {Object.entries(VALUE_RANGES).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Status</label>
          <select value={filters.status} onChange={update('status')}>
            <option value="">All</option>
            {Object.entries(STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Clearing code</label>
          <select value={filters.clearing_code} onChange={update('clearing_code')}>
            <option value="">All</option>
            {clearingCodes.map((c) => (
              <option key={c.code} value={c.code}>{`${c.code} — ${c.full_form}`}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>Root cause</label>
          <select value={filters.category} onChange={update('category')}>
            <option value="">All</option>
            {taxonomy.map((t) => (
              <option key={t.category} value={t.category}>{t.category}</option>
            ))}
          </select>
        </div>
        <div className="field">
          <label>From</label>
          <input type="date" value={filters.date_from} onChange={update('date_from')} />
        </div>
        <div className="field">
          <label>To</label>
          <input type="date" value={filters.date_to} onChange={update('date_to')} />
        </div>
        <button className="secondary" onClick={resetFilters}>Reset</button>
        <button
          onClick={runBatch}
          disabled={busy}
          title={
            filtered
              ? 'Sends the filtered exceptions that have investigation notes but no root cause yet to the AI'
              : 'Sends every exception that has investigation notes but no root cause yet to the AI'
          }
        >
          {busy
            ? 'Analyzing root causes…'
            : filtered
              ? 'Find root causes (filtered)'
              : 'Find root causes (all records)'}
        </button>
      </div>

      {error && <p className="error">{error}</p>}

      <div className="panel">
        {loading ? (
          <p className="muted">Loading…</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Exception #</th>
                <th>PRO</th>
                <th>Date</th>
                <th>Origin</th>
                <th>Dest</th>
                <th>Commodity</th>
                <th>Value</th>
                <th>Status</th>
                <th>Clearing</th>
                <th>Root cause</th>
                <th>Conf.</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((row) => (
                <tr key={row.id}>
                  <td>
                    <Link to={`/exceptions/${row.id}`}>{row.source_osd_number ?? '—'}</Link>
                  </td>
                  <td>{row.pro_number}</td>
                  <td>{formatDateOnly(row.created_at)}</td>
                  <td>{row.origin_terminal}</td>
                  <td>{row.destination_terminal}</td>
                  <td title={row.commodity_code}>{commodityLabel(row)}</td>
                  <td>{VALUE_RANGES[row.value_range]}</td>
                  <td>{STATUS_LABELS[row.status] || row.status}</td>
                  <td>{row.clearing_code || '—'}</td>
                  <td>{row.latest_category || <span className="muted">Unclassified</span>}</td>
                  <td>{row.latest_confidence != null ? row.latest_confidence.toFixed(2) : '—'}</td>
                  <td><SourceBadge source={row.latest_source} /></td>
                </tr>
              ))}
              {data.items.length === 0 && (
                <tr><td colSpan={12} className="muted">No exceptions match these filters.</td></tr>
              )}
            </tbody>
          </table>
        )}

        <div className="pagination">
          <span className="muted">
            Showing {firstRow}–{lastRow} of {data.total}
          </span>
          <div className="pagination-controls">
            <label htmlFor="page-size">Rows</label>
            <select
              id="page-size"
              value={pageSize}
              onChange={(event) => {
                setPage(0);
                setPageSize(Number(event.target.value));
              }}
            >
              {PAGE_SIZES.map((size) => (
                <option key={size} value={size}>{size}</option>
              ))}
            </select>
            <button
              className="secondary"
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0 || loading}
            >
              Previous
            </button>
            <span className="muted">Page {page + 1} of {pageCount}</span>
            <button
              className="secondary"
              onClick={() => setPage((p) => p + 1)}
              disabled={page + 1 >= pageCount || loading}
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
