// SPDX-License-Identifier: Apache-2.0

// Database timestamps (TIMESTAMP WITHOUT TIME ZONE, written as UTC by the
// schema defaults and by the console) arrive without a zone designator, e.g.
// "2026-09-27T11:15:57.575959". JavaScript would read those as local time, so
// they are interpreted as UTC here and rendered in the viewer's own time zone.
// Values that already carry a zone ("Z" or "+08:00") are used as-is. Stored
// values are never rewritten.

const ZONELESS = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;

export function parseStoredTimestamp(value: unknown): Date | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  const text = value.trim();
  const iso = ZONELESS.test(text) ? `${text.replace(' ', 'T')}Z` : text;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** Local date and time for display; `fallback` when absent or unparseable. */
export function formatTimestamp(value: unknown, fallback = 'Unknown'): string {
  const date = parseStoredTimestamp(value);
  return date ? date.toLocaleString() : fallback;
}

export function formatDate(value: unknown, fallback = 'Unknown'): string {
  const date = parseStoredTimestamp(value);
  return date ? date.toLocaleDateString() : fallback;
}

/** Viewer's configured or detected IANA timezone identifier (e.g. 'Asia/Singapore', 'America/New_York'). */
export function getViewerTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/**
 * Validates an IANA time zone name (e.g. 'Asia/Singapore') recognised by Intl.
 * Offset strings such as '+05:00' are rejected: Postgres reads them as POSIX zones with the sign reversed.
 */
export function isValidTimeZone(tz: unknown): tz is string {
  if (typeof tz !== 'string' || !/^[A-Za-z][A-Za-z0-9_+\-/]*$/.test(tz)) return false;
  try {
    Intl.DateTimeFormat(undefined, { timeZone: tz });
    return true;
  } catch {
    return false;
  }
}
