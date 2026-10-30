// SPDX-License-Identifier: Apache-2.0

// Browser-side calls to the official-revision route. Both throw an Error whose
// message is the route's own, such as the agent being unreachable.

async function send(incidentId: string, method: 'PUT' | 'DELETE', revisionId?: number): Promise<void> {
  const response = await fetch(`/api/videos/${encodeURIComponent(incidentId)}/official`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: revisionId === undefined ? undefined : JSON.stringify({ revisionId }),
  });
  const payload = (await response.json().catch(() => ({}))) as { error?: string };
  if (!response.ok) throw new Error(payload.error || 'Update failed');
}

export const markOfficial = (incidentId: string, revisionId: number) => send(incidentId, 'PUT', revisionId);
export const clearOfficial = (incidentId: string) => send(incidentId, 'DELETE');
