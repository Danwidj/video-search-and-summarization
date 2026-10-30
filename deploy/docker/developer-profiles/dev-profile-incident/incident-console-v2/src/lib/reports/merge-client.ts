// SPDX-License-Identifier: Apache-2.0

// Browser-side call to the merge route. Throws an Error whose message is the route's own.

/** Merges the source incident into the target, which is kept; the source is deleted. */
export async function mergeIncidentInto(sourceIncidentId: number, targetIncidentId: number): Promise<void> {
  const response = await fetch(`/api/reports/${encodeURIComponent(String(targetIncidentId))}/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ sourceIncidentId }),
  });
  const payload = (await response.json().catch(() => ({}))) as { error?: string };
  if (!response.ok) throw new Error(payload.error || 'Could not merge the incidents');
}
