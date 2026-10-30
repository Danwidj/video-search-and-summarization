// SPDX-License-Identifier: Apache-2.0

// Store searchable crops on an incident: after a new revision is saved, stores its evidence crops when it is the
// incident's searchable revision.

import { incidentCrops } from '@/modules/reports/application/incident-crops';
import type { SearchableCropsResult } from '@/modules/reports/application/store-searchable-crops';
import type { EmbedEvidence } from '@/modules/reports/application/types';
import type { IncidentId, IncidentReportRepository } from '@/modules/reports/domain/IncidentReportRepository';

/**
 * When `revisionId` is now the incident's searchable revision (no official revision, and it is the newest),
 * embeds its images per camera and stores its crops. Otherwise nothing changes. The revision is already saved,
 * so a failure is returned, never thrown: marking the revision official rebuilds the crops.
 */
export async function storeIncidentSearchableCrops(
  incidentReports: Pick<IncidentReportRepository, 'getIncident' | 'getRevision' | 'setRevisionCrops'>,
  incidentId: IncidentId,
  revisionId: number,
  embed: EmbedEvidence,
): Promise<SearchableCropsResult> {
  try {
    const incident = await incidentReports.getIncident(incidentId);
    if (!incident || incident.officialRevisionId !== null) return { crops: null };
    const record = await incidentReports.getRevision(incidentId, null);
    if (!record || record.revision.revisionId !== revisionId) return { crops: null };
    const crops = await incidentCrops(record.envelope, record.evidence, record.revision.videoNames, incident.videos, embed);
    return { crops: await incidentReports.setRevisionCrops(incidentId, revisionId, crops) };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Could not store the evidence crops of revision ${revisionId} of incident ${incidentId}: ${message}`);
    return { crops: null, error: message };
  }
}
