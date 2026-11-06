// SPDX-License-Identifier: Apache-2.0

import { createHash } from 'node:crypto';

/** SHA-256 (lower-case hex) of the bytes of a Blob, read as a stream so a multi-gigabyte upload is not copied. */
export async function sha256OfBlob(blob: Blob): Promise<string> {
  const hash = createHash('sha256');
  const reader = blob.stream().getReader();
  for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) hash.update(chunk.value);
  return hash.digest('hex');
}
