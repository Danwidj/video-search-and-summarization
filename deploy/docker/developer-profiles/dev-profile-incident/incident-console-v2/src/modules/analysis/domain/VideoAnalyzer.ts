// SPDX-License-Identifier: Apache-2.0

// VideoAnalyzer: the vss-agent's "Agent analyse" contract (plan section 1). The agent
// analyses one video by name, stores the analysis, its crops and the model run, and
// creates no report revision. Only a network failure or a timeout is thrown (as
// AgentRequestError); every HTTP answer becomes a result for the caller to act on.

export interface VideoAnalysisRequest {
  /** The video's real file name, which is also its id. */
  videoName: string;
  /** The video's logical R2 key (no prefix); the agent names its evidence crops after it. */
  videoKey: string;
  model: string;
  /** The reviewer prompt, sent only when present. */
  reviewerPrompt: string | null;
  /** The readable model-run id (`<video name>@<UTC timestamp>`). */
  modelRunId: string;
  /** The length read from the MP4 header; null when unknown (the agent then reads it itself). */
  videoDurationSeconds: number | null;
}

export type VideoAnalysisResult =
  | {
      kind: 'analysed';
      analysisId: number;
      modelRunId: string;
      /** The agent's word for how the run ended, passed through as sent. */
      outcome: string;
      /** The contract-valid incident-contract-v4 payload. */
      payload: Record<string, unknown>;
    }
  | {
      /** HTTP 422: the model's output broke the incident contract; nothing was stored. */
      kind: 'contract_refused';
      message: string;
      rawOutput: string | null;
      finishReason: string | null;
      model: string | null;
      contractVersion: string | null;
    }
  | { kind: 'failed'; status: number; message: string };

export interface VideoAnalyzer {
  analyze(request: VideoAnalysisRequest, signal: AbortSignal): Promise<VideoAnalysisResult>;
}
