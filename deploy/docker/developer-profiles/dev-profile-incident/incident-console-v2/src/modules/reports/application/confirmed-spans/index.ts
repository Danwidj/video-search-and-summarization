// SPDX-License-Identifier: Apache-2.0

// Confirmed spans: the detector-confirmed time range of each instrument and asset track, which sets the item's slice
// (evidenceSlice). People's slices come from the entry itself, so their tracks are not read.

import type { ReadStoredJson } from '@/modules/reports/application/types';
import type { EvidenceEntry } from '@/modules/reports/domain/revision';
import { type ConfirmedSpan, confirmedSpan } from '@/modules/reports/domain/track';

const TRACK_KEY = /^evidence\/.+-track\.json$/;

/**
 * The confirmed span of each image-bearing instrument and asset whose entry names a track, keyed `type:id`. An item whose
 * track has no confirmed sample is left out (its slice falls back to the box second). Without `read` nothing is read, and a
 * track that cannot be read is left out too: a slice is a convenience and must not stop a save or a repair.
 */
export async function confirmedSpans(evidence: EvidenceEntry[], read?: ReadStoredJson): Promise<Map<string, ConfirmedSpan>> {
  const spans = new Map<string, ConfirmedSpan>();
  if (!read) return spans;
  await Promise.all(
    evidence.map(async (entry) => {
      if (entry.item_type === 'entity' || !entry.image || typeof entry.track !== 'string' || !TRACK_KEY.test(entry.track)) return;
      try {
        const span = confirmedSpan(await read(entry.track));
        if (span) spans.set(`${entry.item_type}:${entry.item_id}`, span);
      } catch {
        // No span: the slice uses the box second.
      }
    }),
  );
  return spans;
}
