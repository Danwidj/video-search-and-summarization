// SPDX-License-Identifier: Apache-2.0

// What follows a join decision, whoever made it: the reviewer's Accept or Reject today, an automatic
// rule later. The decision is saved first; these steps then build the report of each incident the
// decision leaves, once nothing on that incident is still undecided.

export interface BuildAfterDecisionDeps {
  /** Whether any pending suggestion still names the incident; true when that cannot be read. */
  hasPending(incidentId: number): Promise<boolean>;
  /** Builds the incident's report from its stored analyses; false when the build failed. */
  build(incidentId: number): Promise<boolean>;
}

/** A merge kept `keptIncidentId`: it is built once, covering every video it now holds. null when other matches on it are undecided. */
export async function buildAfterJoin(deps: BuildAfterDecisionDeps, keptIncidentId: number): Promise<boolean | null> {
  return (await deps.hasPending(keptIncidentId)) ? null : deps.build(keptIncidentId);
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
