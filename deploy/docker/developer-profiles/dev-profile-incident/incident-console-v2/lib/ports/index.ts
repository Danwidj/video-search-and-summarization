// SPDX-License-Identifier: Apache-2.0

export { StoreRejection } from '@/lib/ports/common';
export type { Page, RunKey } from '@/lib/ports/common';
export type { DashboardQuery, DashboardRepository, DashboardSeverity } from '@/lib/ports/dashboard';
export type { DatabaseHealth, HealthRepository } from '@/lib/ports/health';
export type {
  IncidentRepository, OfficialSelectionState, ReportList, ReportListQuery, ReportSort, ReviewState, ReviewTransition, RunReportRecord,
  StructuredEditResult,
} from '@/lib/ports/incidents';
export type {
  CriticVerdict, EvidenceItemType, EvidenceSearchFilters, EvidenceSearchHit, EvidenceSearchRepository, EvidenceSearchRequest, EvidenceSearchResult,
} from '@/lib/ports/search';
export type { OfficialClearance, OfficialSelection, VideoListFilter, VideoListItem, VideoRecord, VideoRepository } from '@/lib/ports/videos';

import type { DashboardRepository } from '@/lib/ports/dashboard';
import type { IncidentRepository } from '@/lib/ports/incidents';
import type { VideoRepository } from '@/lib/ports/videos';

/** What getDbAdapters() returns: one implementation per driven port in use. */
export interface DbAdapters {
  dashboard: DashboardRepository;
  incidents: IncidentRepository;
  videos: VideoRepository;
}
