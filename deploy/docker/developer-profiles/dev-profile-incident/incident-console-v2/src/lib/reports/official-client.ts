// SPDX-License-Identifier: Apache-2.0

// Browser-side calls to the official-revision route. Both throw an Error whose
// message is the route's own, such as the agent being unreachable.

async function send(videoId: string, method: 'PUT' | 'DELETE', revisionId?: number): Promise<void> {
  const response = await fetch(`/api/videos/${encodeURIComponent(videoId)}/official`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: revisionId === undefined ? undefined : JSON.stringify({ revisionId }),
  });
  const payload = (await response.json().catch(() => ({}))) as { error?: string };
  if (!response.ok) throw new Error(payload.error || 'Update failed');
}

export const markOfficial = (videoId: string, revisionId: number) => send(videoId, 'PUT', revisionId);
export const clearOfficial = (videoId: string) => send(videoId, 'DELETE');
