// SPDX-License-Identifier: Apache-2.0

// In-memory VideoAnalyzer for tests: records every request and answers from a script
// (one result per call, the last repeating) or, with none, a deterministic success.

import type { VideoAnalysisRequest, VideoAnalysisResult, VideoAnalyzer } from '@/modules/analysis/infrastructure/agent/video-analyzer';

export class FakeVideoAnalyzer implements VideoAnalyzer {
  readonly requests: VideoAnalysisRequest[] = [];
  private nextAnalysisId = 1;

  private readonly script: Array<VideoAnalysisResult | Error>;
  private readonly payload: Record<string, unknown>;

  /** Results returned in order, the last one repeating; an Error entry is thrown instead. */
  constructor(
    script: Array<VideoAnalysisResult | Error> = [],
    payload: Record<string, unknown> = { incident: { type: 'assault', title: 'Fake incident' } },
  ) {
    this.script = script;
    this.payload = payload;
  }

  async analyze(request: VideoAnalysisRequest, _signal: AbortSignal): Promise<VideoAnalysisResult> {
    const call = this.requests.push(request) - 1;
    const scripted = this.script[Math.min(call, this.script.length - 1)];
    if (scripted instanceof Error) throw scripted;
    if (scripted) return scripted;
    return {
      kind: 'analysed',
      analysisId: this.nextAnalysisId++,
      modelRunId: request.modelRunId,
      outcome: 'stored',
      payload: structuredClone(this.payload),
    };
  }
}
