// SPDX-License-Identifier: Apache-2.0

// Set official revision: marks one revision official, or clears the mark.

import type { DbAdapters } from '@/modules/shared/domain/adapters';
import type { OfficialChange } from '@/modules/videos/domain/VideoRepository';
import { StoreRejection } from '@/modules/shared/domain/common';
import { officialCrops } from '@/modules/reports/domain/revision';
import { confirmedSpans } from '@/modules/reports/application/confirmed-spans';
import { embedSearchableEvidence } from '@/modules/reports/application/embed-searchable-evidence';
import type { EmbedEvidence, ReadStoredJson } from '@/modules/reports/application/types';

/**
 * Marks a revision official (revisionId null clears it). Marking asks the
 * agent to embed the text of the revision's evidence items (as their crop rows
 * store it) and hands the vectors to the store, which rebuilds the incident's evidence_crops in one transaction; a
 * failure leaves the previous official revision and crops untouched.
 */
export async function setOfficialRevision(
  { incidents, videos }: Pick<DbAdapters, 'incidents' | 'videos'>,
  videoId: string,
  revisionId: number | null,
  embed: EmbedEvidence,
  readTrack?: ReadStoredJson,
): Promise<OfficialChange> {
  if (revisionId === null) return videos.setOfficialRevision(videoId, null, []);
  const record = await incidents.getRevision(videoId, revisionId);
  if (!record) throw new StoreRejection('not-found', `Revision not found for this video: ${revisionId}`);
  const embeddings = await embedSearchableEvidence(record.payload, record.evidence, embed);
  return videos.setOfficialRevision(
    videoId,
    revisionId,
    officialCrops(record.payload, record.evidence, embeddings, null, await confirmedSpans(record.evidence, readTrack)),
  );
}
