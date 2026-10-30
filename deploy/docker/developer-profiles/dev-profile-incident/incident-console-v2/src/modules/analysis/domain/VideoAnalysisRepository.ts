// SPDX-License-Identifier: Apache-2.0

// VideoAnalysisRepository: what each analysis run of a video produced. Every
// run is a new row and rows are never changed; the latest row per video wins
// (newest creation time, then highest id).

import type { EvidenceEntry, ReportPayload } from '@/modules/reports/domain/revision';

export interface VideoAnalysis {
  id: number;
  videoId: string;
  modelRunId: string;
  /** The contract-valid report for this one video. */
  payload: ReportPayload;
  evidence: EvidenceEntry[];
  incidentType: string | null;
  severityLevel: number | null;
  startSeconds: number | null;
  endSeconds: number | null;
  /** UTC instant the analysis was stored, ISO 8601. */
  createdAt: string;
}

export interface NewVideoAnalysis {
  videoId: string;
  /** The run must already be recorded. */
  modelRunId: string;
  payload: ReportPayload;
  evidence: EvidenceEntry[];
  /** Search vector for the analysis summary; null or absent stores none. */
  embedding?: number[] | null;
  /** Defaults to now; set only to order rows deterministically. */
  createdAt?: string;
}

export interface VideoAnalysisRepository {
  /** Appends an analysis (facet fields come from the payload) and returns it. Throws when the video or the run is unknown. */
  saveAnalysis(analysis: NewVideoAnalysis): Promise<VideoAnalysis>;
  /** The newest analysis of a video, or null when it has none. */
  latestAnalysis(videoId: string): Promise<VideoAnalysis | null>;
  /** The newest analysis of each named video that has one, keyed by video name. */
  latestAnalyses(videoIds: string[]): Promise<Map<string, VideoAnalysis>>;
  /** Every analysis of a video, oldest first. */
  listAnalyses(videoId: string): Promise<VideoAnalysis[]>;
}
