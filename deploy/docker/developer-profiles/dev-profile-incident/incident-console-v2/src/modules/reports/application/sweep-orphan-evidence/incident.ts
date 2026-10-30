// SPDX-License-Identifier: Apache-2.0

// Orphan sweep for one video of an incident: finds, and on request removes, evidence images in R2 that no stored
// record references. The behaviour matches sweepOrphanEvidence; only the references come from the incident.

import type { EvidenceObjectStore } from '@/modules/reports/application/types';
import {
  DEFAULT_SWEEP_AGE_HOURS,
  MIN_SWEEP_AGE_HOURS,
  type SweepOptions,
  type SweepReport,
} from '@/modules/reports/application/sweep-orphan-evidence';
import type { IncidentId, IncidentReportRepository } from '@/modules/reports/domain/IncidentReportRepository';
import { evidenceFolder, isEvidenceKeyOfVideo } from '@/modules/reports/domain/revision';
import { StoreRejection } from '@/modules/shared/domain/common';

export async function sweepIncidentOrphanEvidence(
  incidentReports: Pick<IncidentReportRepository, 'getIncident' | 'listReferencedEvidenceImages'>,
  store: EvidenceObjectStore,
  incidentId: IncidentId,
  videoId: string,
  options: SweepOptions = {},
): Promise<SweepReport> {
  const dryRun = options.dryRun ?? true;
  const minAgeHours = Math.max(options.minAgeHours ?? DEFAULT_SWEEP_AGE_HOURS, MIN_SWEEP_AGE_HOURS);
  const cutoff = (options.now ?? new Date()).getTime() - minAgeHours * 3_600_000;

  const incident = await incidentReports.getIncident(incidentId);
  const video = incident?.videos.find((candidate) => candidate.videoId === videoId);
  if (!video?.storageKey) throw new StoreRejection('not-found', `Video not found in this incident: ${videoId}`);
  const videoKey = video.storageKey;
  // Listed before the references are read: a save that lands in between has its image in the references, and an
  // upload after the listing is not in the list, so a live image is never a candidate.
  const objects = await store.list(evidenceFolder(videoKey));
  const references = await incidentReports.listReferencedEvidenceImages(incidentId, videoId);
  if (references === null) throw new StoreRejection('not-found', `Video not found in this incident: ${videoId}`);
  const referenced = new Set(references);

  const report: SweepReport = {
    videoId,
    dryRun,
    minAgeHours,
    scanned: objects.length,
    referenced: 0,
    tooRecent: 0,
    orphans: [],
    removed: [],
    failed: [],
  };
  for (const { key, lastModified } of objects) {
    if (!isEvidenceKeyOfVideo(key, videoKey)) continue;
    if (referenced.has(key)) report.referenced += 1;
    else if (lastModified === null || lastModified.getTime() > cutoff) report.tooRecent += 1;
    else report.orphans.push(key);
  }
  if (dryRun) return report;

  for (const key of report.orphans) {
    try {
      await store.remove(key);
      report.removed.push(key);
    } catch (error) {
      report.failed.push({ key, error: error instanceof Error ? error.message : String(error) });
    }
  }
  return report;
}
