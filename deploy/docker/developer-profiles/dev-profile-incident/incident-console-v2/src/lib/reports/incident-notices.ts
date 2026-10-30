// SPDX-License-Identifier: Apache-2.0

// The one inline notice that reports a decision on an incident (accept, reject, merge, delete, move). It is kept per
// scope, outlives a page change (the merge lands on another incident) and is cleared when a version is built or dismissed.
// Browser-safe and free of React: the store takes its storage, so tests run it on a Map.

export interface IncidentNotice {
  title: string;
  detail: string;
  /** The incident that kept its id after a merge; the notice links to it where the reader is not already there. */
  keptIncidentId?: number;
}

/** `incident:<id>` for an incident's page, `library` for the Matches tab. */
export type NoticeScope = string;

export const incidentScope = (incidentId: number): NoticeScope => `incident:${incidentId}`;
export const LIBRARY_SCOPE: NoticeScope = 'library';

export interface NoticeStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

const KEY_PREFIX = 'incident-notice:';

function isNotice(value: unknown): value is IncidentNotice {
  if (typeof value !== 'object' || value === null) return false;
  const { title, detail, keptIncidentId } = value as Record<string, unknown>;
  return typeof title === 'string' && typeof detail === 'string' && (keptIncidentId === undefined || typeof keptIncidentId === 'number');
}

export function createNoticeStore(storage: NoticeStorage | null) {
  const notices = new Map<NoticeScope, IncidentNotice | null>();
  const listeners = new Set<() => void>();

  const read = (scope: NoticeScope): IncidentNotice | null => {
    try {
      const raw = storage?.getItem(KEY_PREFIX + scope);
      const parsed: unknown = raw ? JSON.parse(raw) : null;
      return isNotice(parsed) ? parsed : null;
    } catch {
      return null;
    }
  };
  const write = (scope: NoticeScope, notice: IncidentNotice | null) => {
    notices.set(scope, notice);
    try {
      if (notice) storage?.setItem(KEY_PREFIX + scope, JSON.stringify(notice));
      else storage?.removeItem(KEY_PREFIX + scope);
    } catch {
      // Storage is optional: the notice still shows in this tab.
    }
    for (const listener of listeners) listener();
  };

  return {
    /** The same object until the notice changes, so it can serve as a React snapshot. */
    get(scope: NoticeScope): IncidentNotice | null {
      if (!notices.has(scope)) notices.set(scope, read(scope));
      return notices.get(scope) ?? null;
    },
    set: (scope: NoticeScope, notice: IncidentNotice) => write(scope, notice),
    clear: (scope: NoticeScope) => {
      if (notices.get(scope) !== null || read(scope) !== null) write(scope, null);
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  };
}

function browserStorage(): NoticeStorage | null {
  try {
    return typeof window === 'undefined' ? null : window.sessionStorage;
  } catch {
    return null;
  }
}

/** The page's store, backed by sessionStorage where the browser allows it. */
export const incidentNotices = createNoticeStore(browserStorage());
