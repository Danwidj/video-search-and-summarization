// SPDX-License-Identifier: Apache-2.0

// Orphan sweep: finds, and on request removes, evidence images in R2 that no
// stored record references. Save uploads a replacement image before it writes
// the revision, so a save that fails after the upload leaves an image no
// revision names. An image an older revision names is not an orphan, whatever
// has replaced it since.

import { evidenceFolder, isEvidenceKeyOfVideo } from '@/modules/reports/domain/revision';
import type { IncidentRepository } from '@/modules/reports/domain/IncidentRepository';
import type { VideoRepository } from '@/modules/videos/domain/VideoRepository';
import { StoreRejection } from '@/modules/shared/domain/common';
import type { EvidenceObjectStore } from '@/modules/reports/application/types';

/** An upload this young may belong to a save still in flight, so it is never removed. */
export const MIN_SWEEP_AGE_HOURS = 1;
export const DEFAULT_SWEEP_AGE_HOURS = 24;

export interface SweepOptions {
  /** Default true: report what would be removed and remove nothing. */
  dryRun?: boolean;
  /** Only objects older than this are candidates; raised to MIN_SWEEP_AGE_HOURS when lower. */
  minAgeHours?: number;
  now?: Date;
}

export interface SweepReport {
  videoId: string;
  dryRun: boolean;
  minAgeHours: number;
  /** Objects found under evidence/<video key>/. */
  scanned: number;
  /** Objects a revision or evidence_crops row names. */
  referenced: number;
  /** Unreferenced objects too young to remove (or with no known age). */
  tooRecent: number;
  /** Unreferenced objects old enough to remove. */
  orphans: string[];
  /** Orphans removed; always empty on a dry run. */
  removed: string[];
  /** Orphans whose removal failed, with the reason. */
  failed: Array<{ key: string; error: string }>;
}

export async function sweepOrphanEvidence(
  { incidents, videos }: { incidents: Pick<IncidentRepository, 'listReferencedEvidenceImages'>; videos: Pick<VideoRepository, 'getVideo'> },
  store: EvidenceObjectStore,
  videoId: string,
  options: SweepOptions = {},
): Promise<SweepReport> {
  const dryRun = options.dryRun ?? true;
  const minAgeHours = Math.max(options.minAgeHours ?? DEFAULT_SWEEP_AGE_HOURS, MIN_SWEEP_AGE_HOURS);
  const cutoff = (options.now ?? new Date()).getTime() - minAgeHours * 3_600_000;

  // The objects are listed before the references are read: a save that lands in
  // between has its image in the references, and an upload after the listing is
  // not in the list. Either way a live image is never a candidate.
  const video = await videos.getVideo(videoId);
  if (!video?.storageKey) throw new StoreRejection('not-found', `Video not found: ${videoId}`);
  const videoKey = video.storageKey;
  const objects = await store.list(evidenceFolder(videoKey));
  const references = await incidents.listReferencedEvidenceImages(videoId);
  if (references === null) throw new StoreRejection('not-found', `Video not found: ${videoId}`);
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
