// SPDX-License-Identifier: Apache-2.0

// Build report (Regenerate): a new AI version of an incident from the latest stored
// analysis of each of its current videos. Nothing is re-analysed: the agent only
// synthesises the incident overview from the stored payloads, and the version covers
// exactly the incident's current videos. It also builds the first version of an
// incident that has none. A video with no analysis stops the build before anything
// is written, because the coverage would otherwise not be the incident's videos.

import { AgentRequestError } from '@/modules/analysis/domain/IncidentAgent';
import { incidentRunSubject, modelRunId, type ModelRunRepository } from '@/modules/analysis/domain/ModelRunRepository';
import type { VideoAnalysis, VideoAnalysisRepository } from '@/modules/analysis/domain/VideoAnalysisRepository';
import type { IncidentVideoRepository } from '@/modules/videos/domain/IncidentVideoRepository';
import { envelopePayload, normaliseOverview } from '@/modules/reports/domain/envelope';
import type { IncidentId, IncidentReportRepository } from '@/modules/reports/domain/IncidentReportRepository';
import type { EvidenceEntry } from '@/modules/reports/domain/revision';
import { StoreRejection } from '@/modules/shared/domain/common';

/** The recorded name of a synthesis run whose analyses name no model. */
const FALLBACK_MODEL = 'incident-synthesis';

/** The build was refused or failed before a version was written; status is the HTTP status to answer with. */
export class BuildReportError extends Error {
  status: number;
  details?: Record<string, unknown>;

  constructor(status: number, message: string, details?: Record<string, unknown>) {
    super(message);
    this.name = 'BuildReportError';
    this.status = status;
    this.details = details;
  }
}

/** The agent's synthesis (the "Agent synthesise" contract): one overview and its search embedding from each video's analysis. */
export type Synthesis =
  | { kind: 'synthesised'; overview: Record<string, unknown>; embedding: number[] }
  | { kind: 'failed'; status: number; message: string };

export interface IncidentSynthesizerPort {
  synthesize(videos: Array<{ videoName: string; payload: Record<string, unknown> }>, signal: AbortSignal): Promise<Synthesis>;
}

export interface BuildReportPorts {
  incidents: IncidentReportRepository;
  videos: IncidentVideoRepository;
  analyses: VideoAnalysisRepository;
  modelRuns: ModelRunRepository;
  /** Null when the agent is not configured. */
  synthesizer: IncidentSynthesizerPort | null;
  now?: () => Date;
  /** Bounds the synthesis call. */
  signal?: () => AbortSignal;
}

export interface BuiltReport {
  incidentId: IncidentId;
  revisionId: number;
  revisionNo: number;
  modelRunId: string;
  /** The coverage: every current video of the incident, in the order of its cameras. */
  videoNames: string[];
  /** Crop rows carried onto the new version from the covered videos. */
  crops: number;
}

const SYNTHESIS_TIMEOUT_MS = 120_000;

const distinct = (values: Array<string | null | undefined>): string[] => [
  ...new Set(values.filter((value): value is string => Boolean(value))),
];

/** Each entry names its camera, because item ids (E1, I1, ...) repeat across the videos' analyses. */
function evidenceOf(analysis: VideoAnalysis): EvidenceEntry[] {
  return analysis.evidence.map((entry) => ({ ...entry, video: analysis.videoId }));
}

export async function buildIncidentReport(
  ports: BuildReportPorts,
  input: { incidentId: IncidentId; note?: string | null },
): Promise<BuiltReport> {
  const { incidentId } = input;
  const videos = await ports.videos.listVideos(incidentId);
  if (!videos.length) {
    if (!(await ports.incidents.getIncident(incidentId))) throw new StoreRejection('not-found', `Incident not found: ${incidentId}`);
    throw new BuildReportError(422, `Incident ${incidentId} has no videos to build a report from`);
  }
  const names = videos.map((video) => video.videoId);
  const latest = await ports.analyses.latestAnalyses(names);
  const unanalysed = names.filter((name) => !latest.has(name));
  if (unanalysed.length) {
    throw new BuildReportError(409, `No analysis is stored for: ${unanalysed.join(', ')}. Analyse them first.`, { videos: unanalysed });
  }
  const analyses = names.map((name) => latest.get(name) as VideoAnalysis);

  if (!ports.synthesizer) throw new BuildReportError(503, 'INCIDENT_AGENT_BASE_URL is not configured');
  const signal = ports.signal?.() ?? AbortSignal.timeout(SYNTHESIS_TIMEOUT_MS);
  let synthesis: Synthesis;
  try {
    synthesis = await ports.synthesizer.synthesize(
      analyses.map((analysis) => ({ videoName: analysis.videoId, payload: analysis.payload })),
      signal,
    );
  } catch (error) {
    if (error instanceof AgentRequestError) throw new BuildReportError(error.code === 'AGENT_TIMEOUT' ? 504 : 502, error.message);
    throw error;
  }
  if (synthesis.kind === 'failed') throw new BuildReportError(502, `The agent could not synthesise the incident: ${synthesis.message}`);

  const runs = await Promise.all(analyses.map((analysis) => ports.modelRuns.getRun(analysis.modelRunId)));
  const at = (ports.now ?? (() => new Date()))();
  const run = {
    id: modelRunId(incidentRunSubject(incidentId), at),
    modelName: distinct(runs.map((candidate) => candidate?.modelName)).join(', ') || FALLBACK_MODEL,
    modelVersion: null,
    promptVersion: distinct(runs.map((candidate) => candidate?.promptVersion))[0] ?? null,
    runAt: at.toISOString(),
    notes: JSON.stringify({
      recordType: 'incident_synthesis',
      incidentId,
      videoNames: names,
      analysisIds: analyses.map((analysis) => analysis.id),
      analysisRunIds: analyses.map((analysis) => analysis.modelRunId),
    }),
  };
  await ports.modelRuns.recordRun(run);

  const created = await ports.incidents.createAiRevision({
    incidentId,
    modelRunId: run.id,
    note: input.note?.trim() || null,
    payload: envelopePayload({
      overview: normaliseOverview(synthesis.overview),
      cameras: analyses.map((analysis) => ({ video: analysis.videoId, report: analysis.payload })),
    }),
    evidence: analyses.flatMap(evidenceOf),
    videoNames: names,
    embedding: synthesis.embedding,
  });
  return {
    incidentId,
    revisionId: created.revisionId,
    revisionNo: created.revisionNo,
    modelRunId: run.id,
    videoNames: names,
    crops: created.crops,
  };
}
