// SPDX-License-Identifier: Apache-2.0

// In-memory VideoAnalysisRepository for tests. Like the database it refuses an
// analysis whose video or run is unknown, and keeps every analysis (latest wins).

import type { ModelRunRepository } from '@/modules/analysis/domain/ModelRunRepository';
import type { NewVideoAnalysis, VideoAnalysis, VideoAnalysisRepository } from '@/modules/analysis/domain/VideoAnalysisRepository';
import { revisionFacets } from '@/modules/reports/domain/revision';

export class InMemoryVideoAnalysisRepository implements VideoAnalysisRepository {
  readonly analyses: VideoAnalysis[] = [];
  private nextId = 1;
  private readonly videoIds: Set<string>;
  private readonly runs: ModelRunRepository;

  /** videoIds: the videos that exist; runs: where the runs are recorded. */
  constructor(videoIds: Iterable<string>, runs: ModelRunRepository) {
    this.videoIds = new Set(videoIds);
    this.runs = runs;
  }

  async saveAnalysis(analysis: NewVideoAnalysis): Promise<VideoAnalysis> {
    if (!this.videoIds.has(analysis.videoId)) throw new Error(`unknown video: ${analysis.videoId}`);
    if (!(await this.runs.getRun(analysis.modelRunId))) throw new Error(`unknown model run: ${analysis.modelRunId}`);
    const facets = revisionFacets(analysis.payload);
    const stored: VideoAnalysis = {
      id: this.nextId++,
      videoId: analysis.videoId,
      modelRunId: analysis.modelRunId,
      payload: structuredClone(analysis.payload),
      evidence: structuredClone(analysis.evidence),
      incidentType: facets.incident_type,
      severityLevel: facets.severity_level,
      startSeconds: facets.start_seconds,
      endSeconds: facets.end_seconds,
      createdAt: analysis.createdAt ?? new Date().toISOString(),
    };
    this.analyses.push(stored);
    return structuredClone(stored);
  }

  async latestAnalysis(videoId: string): Promise<VideoAnalysis | null> {
    const all = await this.listAnalyses(videoId);
    return all.at(-1) ?? null;
  }

  async latestAnalyses(videoIds: string[]): Promise<Map<string, VideoAnalysis>> {
    const latest = new Map<string, VideoAnalysis>();
    for (const videoId of videoIds) {
      const found = await this.latestAnalysis(videoId);
      if (found) latest.set(videoId, found);
    }
    return latest;
  }

  async listAnalyses(videoId: string): Promise<VideoAnalysis[]> {
    return this.analyses
      .filter((analysis) => analysis.videoId === videoId)
      .sort((a, b) => (a.createdAt === b.createdAt ? a.id - b.id : a.createdAt < b.createdAt ? -1 : 1))
      .map((analysis) => structuredClone(analysis));
  }
}
