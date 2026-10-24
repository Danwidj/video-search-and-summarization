// SPDX-License-Identifier: Apache-2.0

// Uploads one cropped evidence image to R2 through the evidence-image route,
// so Save can send its key. Only the report page's Save calls it.

/** Uploads a JPEG for a draft item and answers the R2 key the server wrote. */
export async function uploadEvidenceImage(videoId: string, itemId: string, blob: Blob): Promise<string> {
  const form = new FormData();
  form.append('file', blob, `${itemId}.jpg`);
  form.append('itemId', itemId);
  const response = await fetch(`/api/reports/${encodeURIComponent(videoId)}/evidence-image`, { method: 'POST', body: form });
  const body = (await response.json().catch(() => null)) as { image?: unknown; error?: string } | null;
  if (!response.ok || typeof body?.image !== 'string') throw new Error(body?.error ?? `The image upload failed (${response.status})`);
  return body.image;
}
