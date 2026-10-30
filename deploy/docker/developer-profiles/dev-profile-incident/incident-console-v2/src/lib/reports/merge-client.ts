// SPDX-License-Identifier: Apache-2.0

// Browser-side calls for a merge. A refusal throws a MergeRequestError, whose message is worded for the reviewer.

/** What the reviewer is told when the merge request is refused, in place of the store's own wording. */
export function mergeFailureMessage(status: number | null, fallback: string): string {
  if (status === 404) return 'One of these incidents no longer exists, so nothing was merged. Close this and refresh the library.';
  if (status === 422) return 'These incidents cannot be merged, so nothing was changed. Choose another incident.';
  return fallback || 'Could not merge the incidents. Nothing was changed.';
}

/** Raised by the browser calls with the HTTP status the route answered, so the dialog can word it. */
export class MergeRequestError extends Error {
  readonly status: number | null;

  constructor(status: number | null, message: string) {
    super(mergeFailureMessage(status, message));
    this.name = 'MergeRequestError';
    this.status = status;
  }
}

async function checked(response: Response, fallback: string): Promise<void> {
  if (response.ok) return;
  const payload = (await response.json().catch(() => ({}))) as { error?: string };
  throw new MergeRequestError(response.status, payload.error || fallback);
}

const post = (path: string, body: unknown) =>
  fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).catch(() => {
    throw new MergeRequestError(null, 'Could not reach the server, so nothing was merged. Try again.');
  });

/** Merges the source incident into the target, which is kept; the source is deleted. */
export async function mergeIncidentInto(sourceIncidentId: number, targetIncidentId: number): Promise<void> {
  await checked(
    await post(`/api/reports/${encodeURIComponent(String(targetIncidentId))}/merge`, { sourceIncidentId }),
    'Could not merge the incidents',
  );
}

/** Accepts a suggestion: the pair merges and `keptIncidentId` keeps its id. */
export async function acceptSuggestionRequest(suggestionId: number, keptIncidentId: number): Promise<void> {
  await checked(await post(`/api/suggestions/${suggestionId}/accept`, { incidentId: keptIncidentId }), 'Could not accept the match');
}

/** Builds the incident's report from its stored analyses; false when the build failed. */
export async function requestReportBuild(incidentId: number): Promise<boolean> {
  try {
    const response = await fetch(`/api/reports/${encodeURIComponent(String(incidentId))}/build`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: '{}',
    });
    return response.ok;
  } catch {
    return false;
  }
}

export interface IncidentVideos {
  videoNames: string[];
  hasOfficial: boolean;
}

/** The video names of an incident and whether it has an official version; throws an Error when they cannot be read. */
export async function fetchIncidentVideos(incidentId: number, signal?: AbortSignal): Promise<IncidentVideos> {
  const response = await fetch(`/api/reports/${encodeURIComponent(String(incidentId))}/videos`, { cache: 'no-store', signal });
  const payload = (await response.json().catch(() => ({}))) as Partial<IncidentVideos> & { error?: string };
  if (!response.ok || !payload.videoNames) throw new Error(payload.error || 'Could not read the incident');
  return { videoNames: payload.videoNames, hasOfficial: payload.hasOfficial === true };
}
