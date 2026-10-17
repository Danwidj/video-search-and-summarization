// SPDX-License-Identifier: Apache-2.0

// TypeScript 4.9 has no `export type *`, so each type is named.
export { StoreRejection } from '@/lib/ports/common';
export type { Page, RunKey } from '@/lib/ports/common';
export type { DashboardQuery, DashboardRepository } from '@/lib/ports/dashboard';
export type { DatabaseHealth, HealthRepository } from '@/lib/ports/health';
export type {
  IncidentRepository, OfficialSelectionState, ReviewState, RunReportRecord, StructuredEditResult,
} from '@/lib/ports/incidents';
export type { EvidenceCropItem, EvidenceItemType, EvidenceSearchRepository, SearchEvidenceParams, SearchQueryRecord } from '@/lib/ports/search';
export type { OfficialClearance, OfficialSelection, VideoListFilter, VideoListItem, VideoRecord, VideoRepository } from '@/lib/ports/videos';

import type { IncidentRepository } from '@/lib/ports/incidents';
import type { VideoRepository } from '@/lib/ports/videos';

/** What getDbAdapters() returns: one implementation per driven port in use. */
export interface DbAdapters {
  incidents: IncidentRepository;
  videos: VideoRepository;
}
