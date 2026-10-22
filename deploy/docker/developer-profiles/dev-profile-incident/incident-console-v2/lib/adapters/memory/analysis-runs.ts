// SPDX-License-Identifier: Apache-2.0

// In-memory AnalysisRunRepository for tests. It mirrors what the Supabase
// adapter guarantees: a video is recorded once and never reset, a failed
// attempt is a run record only, and a valid run is saved whole and read back
// against the video's storage key.

import type { AnalysisAttemptRecord, AnalysisRunRepository, ContractRunRecord, UploadedVideo } from '@/lib/ports';

export class InMemoryAnalysisRunRepository implements AnalysisRunRepository {
  readonly videos = new Map<string, UploadedVideo>();
  /** Every saved attempt record by model run id, valid or failed. */
  readonly attempts = new Map<string, AnalysisAttemptRecord>();
  /** Valid runs only: the ones with an incident, evidence, a review and a report. */
  readonly runs = new Map<string, ContractRunRecord>();

  constructor(videos: UploadedVideo[] = []) {
    for (const video of videos) this.videos.set(video.videoId, { ...video });
  }

  async recordUploadedVideo(video: UploadedVideo): Promise<void> {
    if (!this.videos.has(video.videoId)) this.videos.set(video.videoId, { ...video });
  }

  async saveFailedAttempt(attempt: AnalysisAttemptRecord): Promise<void> {
    if (attempt.status !== 'contract_failed' && attempt.status !== 'request_failed') {
      throw new Error(`saveFailedAttempt called with a ${attempt.status} attempt`);
    }
    this.attempts.set(attempt.modelRunId, structuredClone(attempt));
  }

  async saveRun(run: ContractRunRecord, onStep: (step: string) => void = () => {}): Promise<void> {
    onStep('saving the run');
    this.attempts.set(run.modelRunId, structuredClone(run));
    this.runs.set(run.modelRunId, structuredClone(run));
    onStep('verifying the saved run');
    const video = this.videos.get(run.videoId);
    if (!video) throw new Error('persistence verification found missing rows: videos');
    if (video.r2Key !== run.r2Key) throw new Error('persistence verification found an unexpected videos.filepath value');
  }
}
