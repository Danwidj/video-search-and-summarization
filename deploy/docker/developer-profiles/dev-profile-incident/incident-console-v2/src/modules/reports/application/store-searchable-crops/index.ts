// SPDX-License-Identifier: Apache-2.0

// Store searchable crops: after a new revision is saved, stores its evidence
// crops when it is the video's searchable revision.

import type { DbAdapters } from '@/modules/shared/domain/adapters';
import { officialCrops } from '@/modules/reports/domain/revision';
import { confirmedSpans } from '@/modules/reports/application/confirmed-spans';
import { embedSearchableEvidence } from '@/modules/reports/application/embed-searchable-evidence';
import type { EmbedEvidence, ReadStoredJson } from '@/modules/reports/application/types';

/** What storing a new revision's crops did: the rows stored, or null when skipped or failed (error says why). */
export interface SearchableCropsResult {
  crops: number | null;
  error?: string;
}

/**
 * After a new revision is saved: when it is now the video's searchable
 * revision (the video has no official revision, so the newest is searched),
 * embeds its images and stores its evidence_crops, so Find evidence returns
 * the video before anyone marks a revision official. With an official
 * revision nothing changes. The revision is already saved, so a failure here
 * is returned, never thrown: the crops can be rebuilt by marking it official.
 */
export async function storeSearchableCrops(
  { incidents, videos }: Pick<DbAdapters, 'incidents' | 'videos'>,
  videoId: string,
  revisionId: number,
  embed: EmbedEvidence,
  readTrack?: ReadStoredJson,
): Promise<SearchableCropsResult> {
  try {
    const video = await videos.getVideo(videoId);
    if (!video || video.officialRevisionId !== null) return { crops: null };
    const record = await incidents.getRevision(videoId, revisionId);
    if (!record) return { crops: null };
    const embeddings = await embedSearchableEvidence(record.payload, record.evidence, embed);
    const spans = await confirmedSpans(record.evidence, readTrack);
    const crops = officialCrops(record.payload, record.evidence, embeddings, null, spans);
    return { crops: (await videos.setRevisionCrops(videoId, revisionId, crops)).crops };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Could not store the evidence crops of revision ${revisionId} of ${videoId}: ${message}`);
    return { crops: null, error: message };
  }
}
