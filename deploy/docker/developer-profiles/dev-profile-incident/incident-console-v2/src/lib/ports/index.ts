// SPDX-License-Identifier: Apache-2.0

export { StoreRejection } from '@/lib/ports/common';
export type { Page, RevisionKey } from '@/lib/ports/common';
export type { ChatCitation, ChatContext, ChatMessage, ChatRequest, ChatResponse, ChatRole } from '@/lib/ports/chat';
export type { DashboardQuery, DashboardRepository, DashboardSeverity } from '@/lib/ports/dashboard';
export type { DatabaseHealth, HealthRepository } from '@/lib/ports/health';
export type { HumanRevisionInput, IncidentRepository, ReportList, ReportListQuery, ReportSort, RevisionRecord } from '@/lib/ports/incidents';
export type {
  CriticVerdict, EvidenceItemType, EvidenceSearchFilters, EvidenceSearchHit, EvidenceSearchRepository, EvidenceSearchRequest, EvidenceSearchResult,
} from '@/lib/ports/search';
export type { RevisionSearchHit, RevisionSearchRepository, RevisionSearchRequest } from '@/lib/ports/revision-search';
export type { OfficialChange, RevisionCropsChange, VideoListFilter, VideoListItem, VideoRecord, VideoRepository } from '@/lib/ports/videos';
export type { OfficialCrop } from '@/lib/reports/revision';

import type { DashboardRepository } from '@/lib/ports/dashboard';
import type { IncidentRepository } from '@/lib/ports/incidents';
import type { VideoRepository } from '@/lib/ports/videos';

/** What getDbAdapters() returns: one implementation per driven port in use. */
export interface DbAdapters {
  dashboard: DashboardRepository;
  incidents: IncidentRepository;
  videos: VideoRepository;
}
