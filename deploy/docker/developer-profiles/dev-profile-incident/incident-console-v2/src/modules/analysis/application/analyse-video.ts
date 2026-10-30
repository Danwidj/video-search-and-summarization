// SPDX-License-Identifier: Apache-2.0

// Analyse one video through the vss-agent (agent mode only). A new upload first gets its
// incident and its video row (real file name, recorded_at when the file carries one); an
// existing video is simply analysed again. The agent stores the analysis, its crops and the
// model run and creates no report revision, so this returns the ids and stops: reports are
// built from stored analyses by their own use case.
//
// The call never outlives the route: the agent gets whatever is left of the deadline (and never
// more than the model's own timeout), so a slow VLM ends as a clear 504 instead of a killed
// request. A new video whose analysis fails is removed again, so a retry under the same name
// starts clean and no empty incident is left behind; the uploaded R2 object is kept.

import { AgentRequestError } from '@/modules/analysis/domain/IncidentAgent';
import { modelRunId } from '@/modules/analysis/domain/ModelRunRepository';
import type { VideoAnalyzer } from '@/modules/analysis/domain/VideoAnalyzer';
import type { VideoObjectStore } from '@/modules/analysis/domain/VideoObjectStore';
import { normalizeAdditionalInstruction } from '@/modules/analysis/application/build-request';
import { AnalysisRequestError, resolveAllowedModel } from '@/modules/analysis/application/run-contract-analysis';
import type { ContractCatalog } from '@/modules/contract/domain/ContractCatalog';
import { StoreRejection } from '@/modules/shared/domain/common';
import type { IncidentVideoRepository } from '@/modules/videos/domain/IncidentVideoRepository';
import { isValidR2Key } from '@/lib/r2/key';

/** The route's maxDuration, less the time left for rolling back and answering. */
export const ANALYSIS_DEADLINE_MS = 345_000;

export interface AnalyseVideoPorts {
  videos: IncidentVideoRepository;
  objects: VideoObjectStore;
  analyzer: VideoAnalyzer;
  catalog: ContractCatalog;
  /** The clock for run ids and the deadline. */
  now: () => Date;
}

export type AnalyseVideoInput = {
  model: unknown;
  /** The reviewer prompt typed in the console. */
  additionalInstruction?: unknown;
} & (
  | {
      /** A video uploaded just now: its incident and row are created here. */
      kind: 'upload';
      /** The real file name after sanitising; becomes videos.id. */
      videoName: string;
      /** The logical R2 key of the uploaded object. */
      storageKey: string;
      sensorId: string;
    }
  | {
      /** A video already in the database gets one more analysis. */
      kind: 'reanalysis';
      videoName: string;
    }
);

export interface AnalyseVideoResult {
  incidentId: number;
  videoName: string;
  analysisId: number;
  modelRunId: string;
  model: string;
  promptVersion: string;
  /** The agent's word for how the run ended, passed through as sent. */
  outcome: string;
}

function reviewerPrompt(value: unknown): string | null {
  try {
    return normalizeAdditionalInstruction(value);
  } catch (error) {
    throw new AnalysisRequestError(400, error instanceof Error ? error.message : String(error));
  }
}

/** Creates the incident and video for a new upload; a name already taken is the caller's conflict. */
async function createUploadedVideo(
  input: Extract<AnalyseVideoInput, { kind: 'upload' }>,
  ports: AnalyseVideoPorts,
  contentLength: number,
  durationSeconds: number | null,
) {
  const recordedAt = await ports.objects.recordedAt(input.storageKey, contentLength);
  try {
    return await ports.videos.createVideo({
      videoId: input.videoName,
      incidentId: null,
      storageKey: input.storageKey,
      recordedAt,
      durationSeconds,
      source: input.sensorId,
    });
  } catch (error) {
    if (error instanceof StoreRejection && error.reason === 'invalid')
      throw new AnalysisRequestError(409, `A video named ${input.videoName} already exists`);
    throw error;
  }
}

export async function analyseVideo(input: AnalyseVideoInput, ports: AnalyseVideoPorts): Promise<AnalyseVideoResult> {
  const deadline = ports.now().getTime() + ANALYSIS_DEADLINE_MS;
  const model = resolveAllowedModel(input.model, ports.catalog);
  const prompt = reviewerPrompt(input.additionalInstruction);
  let operation = 'preparing the analysis';
  let created = false;
  try {
    let storageKey: string;
    let incidentId: number;
    let durationSeconds: number | null;
    if (input.kind === 'upload') {
      if (!isValidR2Key(input.storageKey)) throw new AnalysisRequestError(400, 'The upload has no valid R2 key');
      operation = 'checking the uploaded video';
      const { contentLength } = await ports.objects.verify(input.storageKey).catch((error: unknown) => {
        throw new AnalysisRequestError(
          404,
          `The uploaded video is not in storage: ${error instanceof Error ? error.message : String(error)}`,
        );
      });
      durationSeconds = await ports.objects.durationSeconds(input.storageKey, contentLength);
      operation = 'creating the incident and video';
      const video = await createUploadedVideo(input, ports, contentLength, durationSeconds);
      created = true;
      storageKey = input.storageKey;
      incidentId = video.incidentId;
    } else {
      operation = 'reading the video';
      const video = await ports.videos.getVideo(input.videoName);
      if (!video) throw new AnalysisRequestError(404, `Video not found: ${input.videoName}`);
      if (!isValidR2Key(video.storageKey)) throw new AnalysisRequestError(409, 'This video has no stored R2 object to analyse');
      operation = 'checking the stored video';
      const { contentLength } = await ports.objects.verify(video.storageKey);
      durationSeconds = video.durationSeconds ?? (await ports.objects.durationSeconds(video.storageKey, contentLength));
      storageKey = video.storageKey;
      incidentId = video.incidentId;
    }

    const runId = modelRunId(input.videoName, ports.now());
    const remaining = deadline - ports.now().getTime();
    operation = 'the agent analysis';
    const result = await ports.analyzer.analyze(
      {
        videoName: input.videoName,
        videoKey: storageKey,
        model: model.id,
        reviewerPrompt: prompt,
        modelRunId: runId,
        videoDurationSeconds: durationSeconds,
      },
      AbortSignal.timeout(Math.max(1_000, Math.min(model.timeout_seconds * 1000, remaining))),
    );
    if (result.kind === 'contract_refused') {
      throw new AnalysisRequestError(422, `The model's response did not satisfy the incident contract: ${result.message}`, {
        outcome: 'contract_failed',
        model: result.model ?? model.id,
        finishReason: result.finishReason,
        rawContent: result.rawOutput?.slice(0, 20000) ?? null,
        attemptId: runId,
      });
    }
    if (result.kind === 'failed')
      throw new AnalysisRequestError(
        502,
        `The agent could not analyse the video (HTTP ${result.status}): ${result.message.slice(0, 400)}`,
        {
          agentStatus: result.status,
        },
      );
    return {
      incidentId,
      videoName: input.videoName,
      analysisId: result.analysisId,
      modelRunId: result.modelRunId,
      model: model.id,
      promptVersion: ports.catalog.contractVersion(),
      outcome: result.outcome,
    };
  } catch (error) {
    if (created) await ports.videos.removeVideo(input.videoName).catch(() => undefined);
    if (error instanceof AnalysisRequestError) throw error;
    if (error instanceof AgentRequestError)
      throw new AnalysisRequestError(
        error.code === 'AGENT_TIMEOUT' ? 504 : 502,
        error.code === 'AGENT_TIMEOUT'
          ? `The agent did not finish the analysis in time: ${error.message}`
          : `The agent could not be reached: ${error.message}`,
        { outcome: 'request_failed' },
      );
    if (error instanceof StoreRejection) throw new AnalysisRequestError(error.reason === 'not-found' ? 404 : 422, error.message);
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(`${operation} failed: ${detail}`);
  }
}
