// SPDX-License-Identifier: Apache-2.0

import type { DashboardRepository } from '@/modules/dashboard/domain/DashboardRepository';
import type { IncidentRepository } from '@/modules/reports/domain/IncidentRepository';
import type { VideoRepository } from '@/modules/videos/domain/VideoRepository';

/** What getDbAdapters() returns: one implementation per driven port in use. */
export interface DbAdapters {
  dashboard: DashboardRepository;
  incidents: IncidentRepository;
  videos: VideoRepository;
}
