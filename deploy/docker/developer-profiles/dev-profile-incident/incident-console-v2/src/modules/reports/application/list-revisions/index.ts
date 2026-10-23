// SPDX-License-Identifier: Apache-2.0

// List revisions: the incident's History, every revision newest first.

import type { IncidentRepository } from '@/modules/reports/domain/IncidentRepository';
import type { RevisionSummary } from '@/modules/reports/domain/revision';

/** The incident's History: every revision, newest first. */
export function listRevisions(incidents: IncidentRepository, videoId: string): Promise<RevisionSummary[]> {
  return incidents.listRevisions(videoId);
}
