// SPDX-License-Identifier: Apache-2.0

// Merge one incident into another.

import type { IncidentId, IncidentReportRepository, MergeResult } from '@/modules/reports/domain/IncidentReportRepository';

/**
 * Moves the source's videos into the target and deletes the source with its revisions. No file moves
 * or goes: the videos keep their R2 keys, and the result's orphanedCropImages are left to the
 * orphan sweep. Throws StoreRejection: 'invalid' for the same incident twice, 'not-found' for an
 * unknown incident.
 */
export function mergeIncidents(
  incidentReports: Pick<IncidentReportRepository, 'mergeIncidents'>,
  targetIncidentId: IncidentId,
  sourceIncidentId: IncidentId,
): Promise<MergeResult> {
  return incidentReports.mergeIncidents(targetIncidentId, sourceIncidentId);
}
