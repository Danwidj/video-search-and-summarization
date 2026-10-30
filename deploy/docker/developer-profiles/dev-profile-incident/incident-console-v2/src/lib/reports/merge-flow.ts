// SPDX-License-Identifier: Apache-2.0

// What a merge is, from the reviewer's side, whoever starts it: the manual merge or a suggestion's Accept. The merge is
// saved first; the kept incident's report is then built once from the stored analyses (no video is analysed again).
// The automatic join of a high-scoring match is not one of these: the batch upload builds that one itself.

import type { IncidentNotice } from '@/lib/reports/incident-notices';

export interface MergeFlowDeps {
  /** Saves the merge; throws when it did not happen. */
  merge(): Promise<void>;
  /** Builds the incident's report; false when the build failed. */
  build(incidentId: number): Promise<boolean>;
}

/** Merges, then builds `keptIncidentId` once. A failed merge builds nothing and throws. Resolves to whether the report was rebuilt. */
export async function mergeThenRebuild(deps: MergeFlowDeps, keptIncidentId: number): Promise<boolean> {
  await deps.merge();
  return deps.build(keptIncidentId);
}

const videos = (count: number) => `${count} ${count === 1 ? 'video' : 'videos'}`;

/** The success message that stays on the kept incident: which incident, how many videos, and whether its report was rebuilt. */
export function mergedNotice(input: { keptIncidentId: number; videoCount: number; rebuilt: boolean }): IncidentNotice {
  const { keptIncidentId, videoCount, rebuilt } = input;
  return {
    title: `Merged into Incident ${keptIncidentId}`,
    detail: rebuilt
      ? `Incident ${keptIncidentId} now holds ${videos(videoCount)}. Its report was rebuilt from all of them.`
      : `Incident ${keptIncidentId} now holds ${videos(videoCount)}, but its report could not be rebuilt. Press Regenerate to include them.`,
    keptIncidentId,
  };
}

/** The line that tells the reviewer what the merge does to the kept incident's official version; null when it has none. */
export function officialMergeWarning(
  target: { incidentId: number; hasOfficial: boolean },
  joiningVideoNames: readonly string[],
): string | null {
  if (!target.hasOfficial) return null;
  return `Incident ${target.incidentId}'s official version stays as it is and will not include ${joiningVideoNames.join(', ')} until you star the rebuilt version.`;
}
