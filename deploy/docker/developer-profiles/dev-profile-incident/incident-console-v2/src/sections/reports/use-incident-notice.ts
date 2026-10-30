// SPDX-License-Identifier: Apache-2.0
'use client';

import { useSyncExternalStore } from 'react';

import { type IncidentNotice, incidentNotices, type NoticeScope } from '@/lib/reports/incident-notices';

/** The notice kept for the scope, or null. It follows changes made anywhere on the page and survives a page change. */
export function useIncidentNotice(scope: NoticeScope): IncidentNotice | null {
  return useSyncExternalStore(
    incidentNotices.subscribe,
    () => incidentNotices.get(scope),
    () => null,
  );
}
