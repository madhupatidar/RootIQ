const LEVELS = {
  clear: { cls: 'clear', title: 'Nothing concentrated here' },
  watch: { cls: 'watch', title: 'Worth watching' },
  elevated: { cls: 'elevated', title: 'Known pattern' },
  high: { cls: 'high', title: 'High-risk pattern' },
};

/**
 * Tier 1 — what to watch on freight that is still moving.
 * Read before handling, never on the exception form: once an overage is being logged the
 * failure has already happened and a warning there prevents nothing.
 */
export default function WatchPanel({ result, loading }) {
  if (!result) {
    return (
      <div className="guard guard-idle">
        <span className="guard-title">What to watch</span>
        <p className="guard-body">
          Pick a terminal, lane or commodity — I&apos;ll show which root causes are currently
          concentrated there and what the dock can do about them.
        </p>
      </div>
    );
  }

  const meta = LEVELS[result.clear ? 'clear' : result.risk_level] ?? LEVELS.watch;

  return (
    <div className={`guard guard-${meta.cls}`}>
      <div className="guard-head">
        <span className="guard-title">{meta.title}</span>
        {loading && <span className="guard-spinner">checking…</span>}
      </div>
      <p className="guard-body">{result.message}</p>

      {result.signals.map((signal) => (
        <div className="guard-signal" key={`${signal.cohort}-${signal.category}`}>
          <div className="guard-signal-head">
            <strong>{signal.category}</strong>
            <span className={`badge ${signal.severity === 'high' ? 'review' : 'human'}`}>
              {signal.share}% on {signal.cohort_label}
            </span>
          </div>
          <p className="guard-pattern">{signal.pattern}</p>
          {signal.prevention_action && (
            <p className="guard-action">
              <span>Standing prevention action</span>
              {signal.prevention_action}
            </p>
          )}
        </div>
      ))}

      {result.open_flags.length > 0 && (
        <div className="guard-flags">
          {result.open_flags.map((flag) => (
            <p key={flag.id}>
              <span className="badge review">Open flag</span> {flag.scope_value} · {flag.category} —{' '}
              {flag.suggested_action}
            </p>
          ))}
        </div>
      )}

      {result.actions.length > 0 && (
        <ul className="action-list">
          {result.actions.map((item) => (
            <li key={item.key}>
              <b>{item.label}</b>
              <small>{item.why}</small>
            </li>
          ))}
        </ul>
      )}

      <p className="guard-foot">
        Based on {result.population.classified_exceptions} classified exceptions
        {result.population.window_days ? ` from the last ${result.population.window_days} days` : ''}. No
        AI call — this is a lookup against results that were already computed.
      </p>
    </div>
  );
}
