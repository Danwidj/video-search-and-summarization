// SPDX-License-Identifier: Apache-2.0

// Browser-side Regenerate: one call to the build route, which reads the stored analyses, has the agent combine the
// overview and saves the new version. The route reports no stages, so the progress shown is paced by elapsed time and
// held below 100% until the answer arrives.

export interface RegenerateStage {
  label: string;
  /** Percent shown while this stage is current. */
  percent: number;
  /** Milliseconds after the start at which this stage becomes current. */
  startsAtMs: number;
}

export const REGENERATE_STAGES: readonly RegenerateStage[] = [
  { label: 'Reading stored analyses', percent: 25, startsAtMs: 0 },
  { label: 'Combining the overview', percent: 60, startsAtMs: 1500 },
  { label: 'Saving the new version', percent: 90, startsAtMs: 12_000 },
];

/** The stage to show after `elapsedMs`; the last stage stays until the build answers. */
export function regenerateStageAt(elapsedMs: number): RegenerateStage {
  let current = REGENERATE_STAGES[0] as RegenerateStage;
  for (const stage of REGENERATE_STAGES) if (elapsedMs >= stage.startsAtMs) current = stage;
  return current;
}

export interface RegeneratedVersion {
  revisionId: number;
  revisionNo: number;
  videoNames: string[];
}

/** Asks for a new AI version of the incident. Throws an Error carrying the route's own message on failure. */
export async function regenerateReport(incidentId: string, signal?: AbortSignal): Promise<RegeneratedVersion> {
  const response = await fetch(`/api/reports/${encodeURIComponent(incidentId)}/build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
    signal,
  });
  const payload = (await response.json().catch(() => ({}))) as { built?: Partial<RegeneratedVersion>; error?: string };
  const { built } = payload;
  if (!response.ok || !built || typeof built.revisionId !== 'number') {
    throw new Error(payload.error || `Could not build a new version (HTTP ${response.status})`);
  }
  return { revisionId: built.revisionId, revisionNo: Number(built.revisionNo), videoNames: built.videoNames ?? [] };
}

/** The line shown once the new version exists. */
export function regeneratedMessage(version: RegeneratedVersion): string {
  const count = version.videoNames.length;
  return `v${version.revisionNo} created from ${count} video${count === 1 ? '' : 's'} and selected.`;
}

/** The open version leaves out a current video or includes a removed one, so a new version should be built. */
export const needsRegenerate = (coverage: { note: string | null }): boolean => coverage.note !== null;
