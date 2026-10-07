import { useEffect, useState } from 'react';

/** Debounce a value so keystroke-driven lookups don't fire on every character. */
export default function useDebounced(value, delay = 400) {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
