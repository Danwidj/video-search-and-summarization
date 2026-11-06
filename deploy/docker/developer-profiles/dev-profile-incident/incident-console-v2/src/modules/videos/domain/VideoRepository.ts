// SPDX-License-Identifier: Apache-2.0

// VideoRepository: the video registry (1 video = 1 incident), its one official
// revision, and whole-video deletion. R2 objects are never touched here.

import type { Page } from '@/modules/shared/domain/common';
import type { OfficialCrop } from '@/modules/reports/domain/revision';

export type VideoListFilter = 'all' | 'without-report' | 'awaiting-selection' | 'with-report' | 'needs-analysis' | 'failed';

/** One row of a video list. */
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

export interface RevisionCropsChange {
  videoId: string;
  revisionId: number;
  /** evidence_crops rows now stored for the revision (0 when it has none). */
  crops: number;
}

/** One AI report revision of a video with the model run that produced it. */
export interface RevisionRunRecord {
  revisionId: number;
  modelRunId: string;
  incidentType: string | null;
  severityLevel: number | null;
  createdAt: string | null;
  modelName: string | null;
  runDatetime: string | null;
  /** The model run's notes record as stored (JSON text). */
  notes: string | null;
}

/** A model run whose notes name a video: a candidate for a failed attempt in its history. */
export interface AttemptRunRecord {
  modelRunId: string;
  modelName: string | null;
  runDatetime: string | null;
  notes: string | null;
}

/** The stored records behind a video's analysis history, read before the history is built. */
export interface RunHistoryRecords {
  video: VideoRecord;
  revisions: RevisionRunRecord[];
  attempts: AttemptRunRecord[];
  /** Model runs that more than one video uses (batch eval/seed runs). */
  sharedRunIds: Set<string>;
}

/** A searchable revision whose summary has no vector yet: the text to embed is its type, title and description. */
export interface MissingEmbedding {
  videoId: string;
  revisionId: number;
  incidentType: string | null;
  title: string | null;
  description: string | null;
}

export interface VideoRepository {
  listVideos(filter: VideoListFilter, page: number, pageSize: number): Promise<Page<VideoListItem>>;
  getVideo(videoId: string): Promise<VideoRecord | null>;
  /** The video whose uploaded file has this SHA-256 (videos.content_sha256), or null; also null before the column exists. */
  findByContentHash(contentSha256: string): Promise<VideoRecord | null>;
  /** The records a video's analysis history is built from; null for an unknown video. */
  listRunHistory(videoId: string): Promise<RunHistoryRecords | null>;
  /**
   * Makes revisionId the video's one official revision (null clears it) and,
   * in the same transaction, replaces the video's evidence_crops with the
   * given crops (they carry the agent's vectors). Throws StoreRejection: 'not-found' for an unknown
   * video or a revision that is not one of its own.
   */
  setOfficialRevision(videoId: string, revisionId: number | null, crops: OfficialCrop[]): Promise<OfficialChange>;
  /**
   * Replaces the video's evidence_crops with the given crops for revisionId, which must be the
   * video's searchable revision (the official one, else the newest), without changing the
   * official pointer. Throws StoreRejection: 'not-found' for an unknown video, 'invalid' for a
   * revision that is not the searchable one.
   */
  setRevisionCrops(videoId: string, revisionId: number, crops: OfficialCrop[]): Promise<RevisionCropsChange>;
  /**
   * The searchable revisions that have image-bearing evidence but no evidence_crops rows (so the video is missing from
   * Find evidence), optionally only for one video. A video with no such revision is not listed.
   */
  listRevisionsMissingCrops(videoId?: string): Promise<Array<{ videoId: string; revisionId: number }>>;
  /**
   * Stores a repair's crops only when revisionId is still the video's searchable revision and has no crop rows, so a repair
   * never overwrites rows stored meanwhile (by another console, or by the save that raced it). Returns the rows stored, or null
   * when nothing was written.
   */
  repairRevisionCrops(videoId: string, revisionId: number, crops: OfficialCrop[]): Promise<number | null>;
  /**
   * The searchable revisions that have a title or description and no summary vector, so the summary search cannot find them,
   * optionally only for one video. The type, title and description are the text to embed.
   */
  listRevisionsMissingEmbeddings(videoId?: string): Promise<MissingEmbedding[]>;
  /**
   * Stores the summary vector of the video's searchable revision when it has none. Returns false when it already has one.
   * Throws StoreRejection 'invalid' for a revision that is not the searchable one.
   */
  setRevisionEmbedding(videoId: string, revisionId: number, embedding: number[]): Promise<boolean>;
  /** Deletes the video row (its revisions, evidence crops and query results cascade), then the run records that name only this video. */
  deleteVideo(videoId: string): Promise<void>;
}
