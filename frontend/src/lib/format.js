export const VALUE_RANGES = {
  1: '$0 - $250',
  2: '$250 - $1,000',
  3: '> $1,000',
};

export const STATUS_LABELS = {
  exception_entry: 'Exception entry',
  in_progress: 'In progress',
  investigation_complete: 'Investigation complete',
  needs_cleared: 'Needs cleared',
  cleared: 'Cleared',
};

// AS400 timestamps are terminal wall-clock with no zone. The importer stores them as UTC,
// so they must be rendered in UTC too, otherwise the browser shifts every date by its offset.
export const formatDate = (value) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
        timeZone: 'UTC',
      })
    : '—';

export const formatDateOnly = (value) =>
  value
    ? new Date(value).toLocaleDateString(undefined, { dateStyle: 'medium', timeZone: 'UTC' })
    : '—';
