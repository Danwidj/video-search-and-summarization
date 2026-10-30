// SPDX-License-Identifier: Apache-2.0

// What follows a reviewer's Reject: the decision is saved first; this step then builds the first report of each
// incident the decision leaves, once nothing on that incident is still undecided. A join (Accept or the manual merge)
// builds through lib/reports/merge-flow instead.

export interface BuildAfterDecisionDeps {
  /** Whether any pending suggestion still names the incident; true when that cannot be read. */
  hasPending(incidentId: number): Promise<boolean>;
  /** Builds the incident's report from its stored analyses; false when the build failed. */
  build(incidentId: number): Promise<boolean>;
}

/** A pair stays apart: each incident that has no report yet and nothing left to decide gets its first one. */
export async function buildAfterApart(
  deps: BuildAfterDecisionDeps,
  incidents: { incidentId: number; hasReport: boolean }[],
): Promise<boolean[]> {
  const results: boolean[] = [];
  for (const { incidentId, hasReport } of incidents) {
    if (!hasReport && !(await deps.hasPending(incidentId))) results.push(await deps.build(incidentId));
  }
  return results;
}
