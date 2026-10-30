// SPDX-License-Identifier: Apache-2.0

import type { PostgrestClient } from '@/lib/postgrest/client';
import { explicitVideoId } from '@/modules/reports/domain/run-notes';

/**
 * Removes the run records a deleted video leaves behind, once no revision uses them: those whose
 * parsed notes name exactly this video (the notes text match is only a pre-filter), and the agent's,
 * whose notes are empty and whose id starts with "<video id>@". LIKE wildcards in the video id are
 * escaped by the client.
 */
export async function deleteUnusedVideoRuns(db: PostgrestClient, videoId: string): Promise<void> {
  const [byNotes, byId] = await Promise.all([
    db.selectContaining('model_runs', 'notes', `"videoId":"${videoId}"`, 'id,notes'),
    db.selectStartingWith('model_runs', 'id', `${videoId}@`, 'id,notes'),
  ]);
  const seen = new Set<string>();
  for (const candidate of [...byNotes.filter((row) => explicitVideoId(row.notes) === videoId), ...byId]) {
    if (typeof candidate.id !== 'string' || seen.has(candidate.id)) continue;
    seen.add(candidate.id);
    if (await db.selectOne('report_revisions', { model_run_id: candidate.id }, 'id')) continue;
    await db.deleteWhere('model_runs', { id: candidate.id });
  }
}
