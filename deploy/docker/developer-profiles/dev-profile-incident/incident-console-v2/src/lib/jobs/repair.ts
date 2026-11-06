// SPDX-License-Identifier: Apache-2.0

// The automatic repair of searchable versions, run by the analysis job loop (lib/jobs/loop.ts): a searchable version with
// image-bearing evidence and no crop rows, or with no summary vector, is completed without anyone calling
// POST /api/videos/repair-crops. Reasons it is needed: the agent saved a version after the console gave up on the job
// (job 51's came 77 s late), or the agent was down for a human Save.
//
// Each pass is small (REPAIR_BATCH of each kind), silent when nothing is missing, and calls only the agent's embedding
// endpoints. Writes are idempotent and guarded in the database (repair_revision_crops, set_revision_embedding), so several
// consoles may run it at once. A failure is logged and retried after FAILURE_COOLDOWN_MS, so one bad version cannot starve the
// rest; a version whose evidence yields no crop rows is left alone until the console restarts. The pass never throws.

import type { DbAdapters } from '@/modules/shared/domain/adapters';
import { repairMissingCrops } from '@/modules/reports/application/repair-missing-crops';
import { repairMissingEmbeddings } from '@/modules/reports/application/repair-missing-embeddings';
import type { EmbedRevisionEvidence, EmbedSummary, ReadStoredJson } from '@/modules/reports/application/types';

export const REPAIR_INTERVAL_MS = 120_000;
export const REPAIR_BATCH = 5;
export const FAILURE_COOLDOWN_MS = 10 * 60_000;

export interface SearchableRepairDeps {
  db: Pick<DbAdapters, 'incidents' | 'videos'>;
  embedCrops: EmbedRevisionEvidence;
  embedSummary: EmbedSummary;
  readTrack?: ReadStoredJson;
}

export interface SearchableRepairOptions {
  /** The dependencies for one pass; null when the console has no database or agent configured (the pass is then skipped). */
  deps(): SearchableRepairDeps | null;
  log(message: string): void;
  now?(): number;
}

/** Returns the repair pass. A call while a pass is running does nothing. */
export function createSearchableRepair({ deps, log, now = Date.now }: SearchableRepairOptions): () => Promise<void> {
  let running = false;
  const retryAt = new Map<string, number>();
  const settledCrops = new Set<number>();

  const key = (kind: string, revisionId: number) => `${kind}:${revisionId}`;
  const cooling = (kind: string, ids: Iterable<number>): Set<number> => {
    const at = now();
    return new Set([...ids].filter((id) => (retryAt.get(key(kind, id)) ?? 0) > at));
  };
  const failed = (kind: string, item: { videoId: string; revisionId: number }, message: string) => {
    retryAt.set(key(kind, item.revisionId), now() + FAILURE_COOLDOWN_MS);
    log(`repair of ${kind} for video ${item.videoId} revision ${item.revisionId} failed, will retry later: ${message}`);
  };

  return async () => {
    if (running) return;
    running = true;
    try {
      const ports = deps();
      if (!ports) return;
      const { db, embedCrops, embedSummary, readTrack } = ports;

      const missingCrops = await db.videos.listRevisionsMissingCrops();
      const skip = new Set([
        ...settledCrops,
        ...cooling(
          'crops',
          missingCrops.map((item) => item.revisionId),
        ),
      ]);
      if (missingCrops.some((item) => !skip.has(item.revisionId))) {
        const report = await repairMissingCrops(db, embedCrops, { dryRun: false, limit: REPAIR_BATCH, skip }, readTrack);
        for (const item of report.revisions) {
          if (item.error !== undefined) failed('crops', item, item.error);
          else if (item.crops === 0) {
            settledCrops.add(item.revisionId);
            log(`repair found no crops to store for video ${item.videoId} revision ${item.revisionId}`);
          } else if (item.crops !== null)
            log(`repaired the crops of video ${item.videoId} revision ${item.revisionId}: ${item.crops} stored`);
        }
      }

      const missingEmbeddings = await db.videos.listRevisionsMissingEmbeddings();
      const skipEmbeddings = cooling(
        'summary',
        missingEmbeddings.map((item) => item.revisionId),
      );
      if (missingEmbeddings.some((item) => !skipEmbeddings.has(item.revisionId))) {
        const report = await repairMissingEmbeddings(db, embedSummary, { dryRun: false, limit: REPAIR_BATCH, skip: skipEmbeddings });
        for (const item of report.revisions) {
          if (item.error !== undefined) failed('summary', item, item.error);
          else if (item.stored) log(`repaired the summary vector of video ${item.videoId} revision ${item.revisionId}`);
        }
      }
    } catch (error) {
      log(`repair pass failed, will retry: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      running = false;
    }
  };
}
