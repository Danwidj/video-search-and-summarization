// SPDX-License-Identifier: Apache-2.0

import type { DashboardRepository } from '@/lib/ports/dashboard';
import type { IncidentRepository } from '@/lib/ports/incidents';
import type { VideoRepository } from '@/lib/ports/videos';

/** What getDbAdapters() returns: one implementation per driven port in use. */
export interface DbAdapters {
  dashboard: DashboardRepository;
  incidents: IncidentRepository;
  videos: VideoRepository;
}
