// SPDX-License-Identifier: Apache-2.0

// Repair missing crops: stores evidence_crops for every searchable revision that has image-bearing evidence and no crop
// rows, so a video the crop step missed (agent down, a save that failed) appears in Find evidence. Crops stay on whichever
// revision is searchable, official or not.

import type { DbAdapters } from '@/modules/shared/domain/adapters';
import { officialCrops } from '@/modules/reports/domain/revision';
import { confirmedSpans } from '@/modules/reports/application/confirmed-spans';
import type { EmbedRevisionEvidence, ReadStoredJson } from '@/modules/reports/application/types';

export interface RepairedRevision {
  videoId: string;
  revisionId: number;
  /** Rows stored; null on a dry run, a failure, or when nothing was written (see skipped). */
  crops: number | null;
  error?: string;
  /** True when the write was refused because the revision is no longer the searchable one, or crops appeared meanwhile. */
  skipped?: true;
}

export interface RepairReport {
  /** Default true: list what would be repaired and store nothing. */
  dryRun: boolean;
  revisions: RepairedRevision[];
}

/**
 * Embeds and stores the crops of each searchable revision that has none (optionally only videoId's). One revision failing
 * does not stop the rest: its error is in the report. Running it again finds only what is still missing. limit caps the
 * batch; skip names revisions to leave out (the automatic repair's cooldowns).
 */
export async function repairMissingCrops(
  { incidents, videos }: Pick<DbAdapters, 'incidents' | 'videos'>,
  embed: EmbedRevisionEvidence,
  { videoId, dryRun = true, limit, skip }: { videoId?: string; dryRun?: boolean; limit?: number; skip?: ReadonlySet<number> } = {},
  readTrack?: ReadStoredJson,
): Promise<RepairReport> {
  const listed = (await videos.listRevisionsMissingCrops(videoId)).filter((item) => !skip?.has(item.revisionId));
  const missing = limit === undefined ? listed : listed.slice(0, limit);
  if (dryRun) return { dryRun, revisions: missing.map((item) => ({ ...item, crops: null })) };
  const revisions: RepairedRevision[] = [];
  for (const item of missing) {
    try {
      const record = await incidents.getRevision(item.videoId, item.revisionId);
      if (!record) throw new Error('Revision not found');
      const embeddings = await embed(item.revisionId);
      // Written only if the revision is still the searchable one and still has no rows: a repair never overwrites
      // what another console, or a save that raced it, stored meanwhile.
      const stored = await videos.repairRevisionCrops(
        item.videoId,
        item.revisionId,
        officialCrops(record.payload, record.evidence, embeddings, null, await confirmedSpans(record.evidence, readTrack)),
      );
      revisions.push(stored === null ? { ...item, crops: null, skipped: true } : { ...item, crops: stored });
    } catch (error) {
      revisions.push({ ...item, crops: null, error: error instanceof Error ? error.message : String(error) });
    }
  }
  return { dryRun, revisions };
}
