const LABELS = {
  ai_fresh: { text: 'Fresh AI call', cls: 'fresh' },
  cache_hit: { text: 'Served from cache', cls: 'cache' },
  human_override: { text: 'Human override', cls: 'human' },
};

export default function SourceBadge({ source }) {
  if (!source) return <span className="badge">Unclassified</span>;
  const meta = LABELS[source] || { text: source, cls: '' };
  return <span className={`badge ${meta.cls}`}>{meta.text}</span>;
}
