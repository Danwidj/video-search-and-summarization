// SPDX-License-Identifier: Apache-2.0

// Client side of "remove a video from its incident": what the dialog offers, and the two calls it makes.

export type RemoveChoice = 'delete' | 'move';

/** What POST /api/videos/<name>/remove answers (the parts the dialog uses). */
export type RemoveOutcome =
  | { choice: 'delete'; videoId: string; incidentId: number; incidentDeleted: boolean }
  | { choice: 'move'; videoId: string; incidentId: number; newIncidentId: number };

/**
 * The choices the dialog offers. Moving an incident's only video would just rename the incident, so the last video can
 * only be deleted (and the incident goes with it).
 */
export const removeChoices = (videoCount: number): RemoveChoice[] => (videoCount > 1 ? ['move', 'delete'] : ['delete']);

/** "Move" loses nothing, so it is the choice the dialog opens on whenever it is offered. */
export const defaultRemoveChoice = (videoCount: number): RemoveChoice => removeChoices(videoCount)[0];

/** A pick that is no longer offered (the incident shrank while the page stayed open) falls back to the default. */
export const effectiveRemoveChoice = (picked: RemoveChoice, videoCount: number): RemoveChoice =>
  removeChoices(videoCount).includes(picked) ? picked : defaultRemoveChoice(videoCount);

export const isLastVideo = (videoCount: number): boolean => videoCount <= 1;

async function readJson<T>(response: Response, fallback: string): Promise<T> {
  const payload = (await response.json().catch(() => null)) as (T & { error?: string }) | null;
  if (!response.ok || !payload) throw new Error(payload?.error || `${fallback} (HTTP ${response.status})`);
  return payload;
}

/** Removes the video from its incident; 'delete' also removes the incident when it was the last video. */
export async function removeVideo(video: string, choice: RemoveChoice, fetcher: typeof fetch = fetch): Promise<RemoveOutcome> {
  const response = await fetcher(`/api/videos/${encodeURIComponent(video)}/remove`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ choice }),
  });
  const payload = await readJson<{ removed: Omit<RemoveOutcome, 'choice'> & { choice: RemoveChoice } }>(
    response,
    'Could not remove the video',
  );
  return payload.removed as RemoveOutcome;
}

/** Builds an incident's first report from its stored analyses (no video is analysed again). */
export async function buildFirstReport(incidentId: number, fetcher: typeof fetch = fetch): Promise<void> {
  const response = await fetcher(`/api/reports/${encodeURIComponent(String(incidentId))}/build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  });
  await readJson<unknown>(response, 'Could not build the report');
}

/** The page of an incident, for the link shown once its first report exists. */
export const incidentHref = (incidentId: number): string => `/reports/${encodeURIComponent(String(incidentId))}`;
