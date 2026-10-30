// SPDX-License-Identifier: Apache-2.0

// List revisions: the incident's versions, newest first, each with its
// coverage verdict against the videos the incident holds now.

import type { IncidentId, IncidentReportRepository } from '@/modules/reports/domain/IncidentReportRepository';
import { coverageView } from '@/modules/reports/application/report-view';
import type { IncidentVersion } from '@/modules/reports/application/types';

/** The incident's versions, newest first; empty for an unknown incident. */
export async function listRevisions(incidentReports: IncidentReportRepository, incidentId: IncidentId): Promise<IncidentVersion[]> {
  const incident = await incidentReports.getIncident(incidentId);
  if (!incident) return [];
  return incident.revisions.map((revision) => ({ ...revision, coverage: coverageView(revision, incident) }));
}
