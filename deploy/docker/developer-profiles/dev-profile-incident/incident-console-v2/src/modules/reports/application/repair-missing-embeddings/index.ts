// SPDX-License-Identifier: Apache-2.0

// Repair missing summary vectors: embeds the title and description of every searchable revision that has none (a human
// version saved while the agent was down, or an AI version saved without one), so the Find incidents text search can find it.
// The vector is the only thing written, and only into an empty slot.

import type { DbAdapters } from '@/modules/shared/domain/adapters';
import type { EmbedSummary } from '@/modules/reports/application/types';

export interface RepairedEmbedding {
  videoId: string;
  revisionId: number;
  /** True when the vector was stored; false on a dry run, a failure, or when another console stored one first. */
  stored: boolean;
  error?: string;
}

export interface EmbeddingRepairReport {
  dryRun: boolean;
  revisions: RepairedEmbedding[];
}

/**
 * Embeds and stores the summary vector of each searchable revision that has none (optionally only videoId's). One revision
 * failing does not stop the rest. limit caps the batch; skip names revisions to leave out.
 */
export async function repairMissingEmbeddings(
  { videos }: Pick<DbAdapters, 'videos'>,
  embedSummary: EmbedSummary,
  { videoId, dryRun = true, limit, skip }: { videoId?: string; dryRun?: boolean; limit?: number; skip?: ReadonlySet<number> } = {},
): Promise<EmbeddingRepairReport> {
  const listed = (await videos.listRevisionsMissingEmbeddings(videoId)).filter((item) => !skip?.has(item.revisionId));
  const missing = limit === undefined ? listed : listed.slice(0, limit);
  if (dryRun) return { dryRun, revisions: missing.map(({ videoId: id, revisionId }) => ({ videoId: id, revisionId, stored: false })) };
  const revisions: RepairedEmbedding[] = [];
  for (const item of missing) {
    try {
      const embedding = await embedSummary({ title: item.title, description: item.description });
      revisions.push({
        videoId: item.videoId,
        revisionId: item.revisionId,
        stored: await videos.setRevisionEmbedding(item.videoId, item.revisionId, embedding),
      });
    } catch (error) {
      revisions.push({
        videoId: item.videoId,
        revisionId: item.revisionId,
        stored: false,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }
  return { dryRun, revisions };
}
