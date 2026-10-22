// SPDX-License-Identifier: Apache-2.0

// VideoRepository: the video registry, each video's analysis history, its
// official-report selection, and whole-video deletion. R2 objects are never
// touched here.

import type { Page } from '@/lib/ports/common';
import type { OutcomeCounts, RunHistoryEntry } from '@/lib/runs/types';

export type VideoListFilter = 'all' | 'without-report' | 'awaiting-selection';

/** One row of the /videos list. */
export interface VideoListItem {
  videoId: string;
  filename: string;
  uploadedAt: string | null;
  source: string | null;
  /** Analyses with an incident and a report; failed attempts are counted in the video's history. */
  analysesWithReport: number;
  officialRunId: string | null;
}

export interface VideoRecord {
  videoId: string;
  /** videos.filepath as stored: an R2 key for uploads, but legacy rows may hold a VST path (check with isValidR2Key). */
  storageKey: string | null;
  uploadedAt: string | null;
  source: string | null;
  officialRunId: string | null;
}

/** A video and every analysis of it: successful runs, failed attempts and runs whose report was deleted. */
export interface VideoRuns {
  video: VideoRecord;
  /** Newest first; isOfficial marks the video's official run. */
  runs: RunHistoryEntry[];
  counts: OutcomeCounts;
}

export interface OfficialSelection {
  videoId: string;
  officialRunId: string;
  selectedBy: string;
  selectedAt: string;
}

export interface OfficialClearance {
  videoId: string;
  officialRunId: null;
  clearedBy: string;
}

export interface VideoRepository {
  listVideos(filter: VideoListFilter, page: number, pageSize: number): Promise<Page<VideoListItem>>;
  getVideo(videoId: string): Promise<VideoRecord | null>;
  /** Null for an unknown video. Each run's type and severity are the report's as shown: the reviewer's version when it has one. */
  listRuns(videoId: string): Promise<VideoRuns | null>;
  /** Throws StoreRejection: 'not-found' for an unknown video, 'invalid' for a run that cannot be official. */
  selectOfficialRun(videoId: string, modelRunId: string, selectedBy: string): Promise<OfficialSelection>;
  clearOfficialRun(videoId: string, clearedBy: string): Promise<OfficialClearance>;
  /** Deletes the video row (incidents, evidence, reviews and reports cascade), then the run records that name only this video. */
  deleteVideo(videoId: string): Promise<void>;
}
