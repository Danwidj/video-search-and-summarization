// SPDX-License-Identifier: Apache-2.0

// Repair missing crops: stores evidence_crops for every searchable revision that has image-bearing evidence and no crop
// rows, so a video the crop step missed (agent down, a save that failed) appears in Find evidence. Crops stay on whichever
// revision is searchable, official or not.

import type { DbAdapters } from '@/modules/shared/domain/adapters';
import { officialCrops } from '@/modules/reports/domain/revision';
import type { EmbedRevisionEvidence } from '@/modules/reports/application/types';

export interface RepairedRevision {
  videoId: string;
  revisionId: number;
  /** Rows stored; null on a dry run or a failure. */
  crops: number | null;
  error?: string;
}

export interface RepairReport {
  /** Default true: list what would be repaired and store nothing. */
  dryRun: boolean;
  revisions: RepairedRevision[];
}

/**
 * Embeds and stores the crops of each searchable revision that has none (optionally only videoId's). One revision failing
 * does not stop the rest: its error is in the report. Running it again finds only what is still missing.
 */
export async function repairMissingCrops(
  { incidents, videos }: Pick<DbAdapters, 'incidents' | 'videos'>,
  embed: EmbedRevisionEvidence,
  { videoId, dryRun = true }: { videoId?: string; dryRun?: boolean } = {},
): Promise<RepairReport> {
  const missing = await videos.listRevisionsMissingCrops(videoId);
  if (dryRun) return { dryRun, revisions: missing.map((item) => ({ ...item, crops: null })) };
  const revisions: RepairedRevision[] = [];
  for (const item of missing) {
    try {
      const record = await incidents.getRevision(item.videoId, item.revisionId);
      if (!record) throw new Error('Revision not found');
      const embeddings = await embed(item.revisionId);
      const change = await videos.setRevisionCrops(
        item.videoId,
        item.revisionId,
        officialCrops(record.payload, record.evidence, embeddings),
      );
      revisions.push({ ...item, crops: change.crops });
    } catch (error) {
      revisions.push({ ...item, crops: null, error: error instanceof Error ? error.message : String(error) });
    }
  }
  return { dryRun, revisions };
}
