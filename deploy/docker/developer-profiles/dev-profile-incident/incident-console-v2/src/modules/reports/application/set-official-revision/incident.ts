// SPDX-License-Identifier: Apache-2.0

// Set official revision on an incident: marks one revision official, or clears the mark. The searchable crops
// follow the official revision, so marking embeds its evidence first (one call per camera) and rebuilds the
// incident's crops; clearing rebuilds them from the newest revision.

import { incidentCrops } from '@/modules/reports/application/incident-crops';
import type { EmbedEvidence } from '@/modules/reports/application/types';
import type { IncidentId, IncidentOfficialChange, IncidentReportRepository } from '@/modules/reports/domain/IncidentReportRepository';
import { StoreRejection } from '@/modules/shared/domain/common';

type OfficialPort = Pick<IncidentReportRepository, 'getIncident' | 'getRevision' | 'setOfficialRevision' | 'setRevisionCrops'>;

/** Rebuilds the incident's crops from the revision that is searchable now (official, else newest). */
async function rebuildCrops(incidentReports: OfficialPort, incidentId: IncidentId, embed: EmbedEvidence): Promise<number | null> {
  const [incident, record] = await Promise.all([incidentReports.getIncident(incidentId), incidentReports.getRevision(incidentId, null)]);
  if (!incident || !record) return null;
  const crops = await incidentCrops(record.envelope, record.evidence, record.revision.videoNames, incident.videos, embed);
  return incidentReports.setRevisionCrops(incidentId, record.revision.revisionId, crops);
}

/**
 * Marks a revision official. The embeddings are fetched before anything is written, so an unreachable agent
 * leaves the previous official revision and crops untouched. If storing the crops fails after the mark, the
 * previous mark is put back (best effort) and the failure is rethrown.
 */
export async function setIncidentOfficialRevision(
  incidentReports: OfficialPort,
  incidentId: IncidentId,
  revisionId: number,
  embed: EmbedEvidence,
): Promise<IncidentOfficialChange> {
  const [incident, record] = await Promise.all([
    incidentReports.getIncident(incidentId),
    incidentReports.getRevision(incidentId, revisionId),
  ]);
  if (!incident) throw new StoreRejection('not-found', `Incident not found: ${incidentId}`);
  if (!record || record.revision.revisionId !== revisionId) {
    throw new StoreRejection('not-found', `Revision not found for this incident: ${revisionId}`);
  }
  const crops = await incidentCrops(record.envelope, record.evidence, record.revision.videoNames, incident.videos, embed);
  const change = await incidentReports.setOfficialRevision(incidentId, revisionId);
  try {
    await incidentReports.setRevisionCrops(incidentId, revisionId, crops);
  } catch (error) {
    await incidentReports.setOfficialRevision(incidentId, incident.officialRevisionId).catch(() => undefined);
    throw error;
  }
  return change;
}

/**
 * Clears the official mark. The newest revision is searchable again, so its crops are rebuilt; the clear is
 * already stored, so a failure there is logged, not thrown (marking a revision official rebuilds them too).
 */
export async function clearIncidentOfficialRevision(
  incidentReports: OfficialPort,
  incidentId: IncidentId,
  embed: EmbedEvidence,
): Promise<IncidentOfficialChange> {
  const change = await incidentReports.setOfficialRevision(incidentId, null);
  await rebuildCrops(incidentReports, incidentId, embed).catch((error) => {
    console.error(
      `Could not rebuild the evidence crops of incident ${incidentId}: ${error instanceof Error ? error.message : String(error)}`,
    );
  });
  return change;
}
