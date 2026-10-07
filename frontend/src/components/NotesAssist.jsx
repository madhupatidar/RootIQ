import { Link } from 'react-router-dom';

/**
 * Tier 2 — live investigation assist.
 * A nearest-neighbour draft, not the classification. Its main value is the note-quality
 * nudge: better input text produces a better final classification.
 */
export default function NotesAssist({ result, loading }) {
  if (!result || result.status === 'too_short') {
    return (
      <div className="assist assist-idle">
        <span className="assist-title">Investigation assist</span>
        <p className="muted">
          {result?.basis || 'Start typing your findings — I compare them to past classified cases as you go.'}
        </p>
      </div>
    );
  }

  const gaps = result.missing_details ?? [];

  return (
    <div className="assist">
      <div className="assist-head">
        <span className="assist-title">Investigation assist</span>
        {loading && <span className="guard-spinner">matching…</span>}
      </div>

      {result.suggested_category ? (
        <div className="assist-suggestion">
          <div className="assist-suggestion-head">
            <strong>{result.suggested_category}</strong>
            <span className="badge cache">{Math.round(result.confidence * 100)}% match</span>
          </div>
          <p className="muted">{result.basis}</p>
          <p className="assist-disclaimer">{result.disclaimer}</p>
        </div>
      ) : (
        <p className="muted">{result.basis}</p>
      )}

      {result.note_prompts?.length > 0 && (
        <div className="assist-block">
          <span className="assist-label">Worth capturing</span>
          <ul className="assist-list">
            {result.note_prompts.map((prompt) => (
              <li key={prompt}>{prompt}</li>
            ))}
          </ul>
        </div>
      )}

      {gaps.length > 0 ? (
        <div className="assist-block">
          <span className="assist-label">Not mentioned yet</span>
          <ul className="assist-list">
            {gaps.map((gap) => (
              <li key={gap.key}>{gap.label}</li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="assist-complete">
          These notes cover location, identifiers, counts, condition and actions taken. Good to go.
        </p>
      )}

      {result.matches?.length > 0 && (
        <details className="assist-matches">
          <summary>{result.matches.length} similar past case(s)</summary>
          {result.matches.map((match) => (
            <div className="assist-match" key={match.exception_id}>
              <div className="row">
                <Link to={`/exceptions/${match.exception_id}`}>{match.pro_number}</Link>
                <span className="badge">{match.category}</span>
                <span className="muted">{Math.round(match.similarity * 100)}% similar</span>
              </div>
              <p className="muted">{match.snippet}</p>
            </div>
          ))}
        </details>
      )}
    </div>
  );
}
