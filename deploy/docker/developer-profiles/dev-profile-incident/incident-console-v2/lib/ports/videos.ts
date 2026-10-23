// SPDX-License-Identifier: Apache-2.0

// VideoRepository: the video registry (1 video = 1 incident), its one official
// revision, and whole-video deletion. R2 objects are never touched here.

import type { Page } from '@/lib/ports/common';
import type { OfficialCrop } from '@/lib/reports/revision';

export type VideoListFilter = 'all' | 'without-report' | 'awaiting-selection';

/** One row of the /videos list. */
export interface VideoListItem {
  videoId: string;
  filename: string;
  uploadedAt: string | null;
  source: string | null;
  /** Report revisions of the incident, AI and human; failed attempts are counted in the video's history. */
  revisions: number;
  officialRevisionId: number | null;
}

export interface VideoRecord {
  videoId: string;
  /** videos.filepath as stored: an R2 key for uploads, but legacy rows may hold a VST path (check with isValidR2Key). */
  storageKey: string | null;
  uploadedAt: string | null;
  source: string | null;
  officialRevisionId: number | null;
}

export interface OfficialChange {
  videoId: string;
  officialRevisionId: number | null;
  /** evidence_crops rows written for the new official revision (0 when cleared). */
  crops: number;
}

export interface VideoRepository {
  listVideos(filter: VideoListFilter, page: number, pageSize: number): Promise<Page<VideoListItem>>;
  getVideo(videoId: string): Promise<VideoRecord | null>;
  /**
   * Makes revisionId the video's one official revision (null clears it) and,
   * in the same transaction, replaces the video's evidence_crops with the
   * given crops (they carry the agent's vectors). Throws StoreRejection: 'not-found' for an unknown
   * video or a revision that is not one of its own.
   */
  setOfficialRevision(videoId: string, revisionId: number | null, crops: OfficialCrop[]): Promise<OfficialChange>;
  /** Deletes the video row (its revisions, evidence crops and query results cascade), then the run records that name only this video. */
  deleteVideo(videoId: string): Promise<void>;
}
