// SPDX-License-Identifier: Apache-2.0

// In-memory IncidentSynthesizer for tests, mirroring the agent's documented behaviour:
// one video's overview is its own `incident` block limited to the overview fields; with
// several, the earliest start, the latest end and the highest severity win. The embedding
// is a deterministic vector of the right width. A script can force failures instead.

import {
  EMBEDDING_DIMENSIONS,
  type IncidentSynthesizer,
  type SynthesisResult,
  type VideoAnalysisInput,
} from '@/modules/analysis/infrastructure/agent/incident-synthesizer';

const OVERVIEW_FIELDS = [
  'type',
  'title',
  'start_timestamp',
  'end_timestamp',
  'description',
  'severity_level',
  'severity_reason',
  'confidence_score',
  'location',
] as const;

type Incident = Record<string, unknown>;

const incidentOf = (video: VideoAnalysisInput): Incident => (video.payload.incident ?? {}) as Incident;
const numbers = (incidents: Incident[], key: string): number[] =>
  incidents.map((incident) => incident[key]).filter((value): value is number => typeof value === 'number');

function overviewOf(videos: VideoAnalysisInput[]): Record<string, unknown> {
  const incidents = videos.map(incidentOf);
  const first = incidents[0];
  const overview: Record<string, unknown> = {};
  for (const field of OVERVIEW_FIELDS) if (field in first) overview[field] = first[field];
  if (incidents.length === 1) return overview;
  const starts = numbers(incidents, 'start_timestamp');
  const ends = numbers(incidents, 'end_timestamp');
  const severities = numbers(incidents, 'severity_level');
  if (starts.length) overview.start_timestamp = Math.min(...starts);
  if (ends.length) overview.end_timestamp = Math.max(...ends);
  if (severities.length) overview.severity_level = Math.max(...severities);
  return overview;
}

function embeddingOf(overview: Record<string, unknown>): number[] {
  const seed = `${overview.title ?? ''} ${overview.description ?? ''}`.length;
  return Array.from({ length: EMBEDDING_DIMENSIONS }, (_, index) => ((seed + index) % 10) / 10);
}

export class FakeIncidentSynthesizer implements IncidentSynthesizer {
  readonly calls: VideoAnalysisInput[][] = [];

  private readonly script: Array<SynthesisResult | Error>;

  /** Results returned in order, the last one repeating; an Error entry is thrown instead. */
  constructor(script: Array<SynthesisResult | Error> = []) {
    this.script = script;
  }

  async synthesize(videos: VideoAnalysisInput[], _signal: AbortSignal): Promise<SynthesisResult> {
    const call = this.calls.push(videos) - 1;
    const scripted = this.script[Math.min(call, this.script.length - 1)];
    if (scripted instanceof Error) throw scripted;
    if (scripted) return scripted;
    if (videos.length === 0) return { kind: 'failed', status: 422, message: 'videos must hold at least one analysis' };
    const overview = overviewOf(videos);
    return { kind: 'synthesised', overview, embedding: embeddingOf(overview) };
  }
}
