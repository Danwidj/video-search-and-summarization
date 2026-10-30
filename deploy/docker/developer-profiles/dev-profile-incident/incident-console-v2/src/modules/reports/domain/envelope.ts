// SPDX-License-Identifier: Apache-2.0

// The mvp3 revision payload envelope: one overview for the whole incident plus
// one incident-contract-v5 report per camera (video). Pure functions, no I/O:
// parse a stored payload leniently, pick one camera's contract-valid report,
// replace one camera or the overview (the edit saves the whole envelope as a
// new revision) and compute the coverage verdict from the revision's
// video_names against the incident's current videos.

import { validateCore, withoutDerivedFields } from '@/modules/contract/domain/validate';
import { canonicalIncidentType } from '@/modules/reports/domain/normalize';
import type { ReportPayload } from '@/modules/reports/domain/revision';

/** The contract's `incident` block fields, shared by every camera and the overview. */
export interface Overview {
  title: string | null;
  type: string | null;
  severity_level: number | null;
  description: string | null;
  location: string | null;
}

export interface Camera {
  /** The real video file name. */
  video: string;
  /** A report as stored (read leniently; use cameraReport for a contract-valid one). */
  report: ReportPayload;
}

export interface ReportEnvelope {
  overview: Overview;
  cameras: Camera[];
}

type Row = Record<string, unknown>;

const asRow = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});
const text = (value: unknown): string | null => (typeof value === 'string' && value.trim() ? value.trim() : null);

/** A severity of 1-5 as an integer, else null. */
const severity = (value: unknown): number | null =>
  typeof value === 'number' && Number.isInteger(value) && value >= 1 && value <= 5 ? value : null;

/** The overview fields from any object, with legacy incident types mapped to the contract's and absent values null. */
export function normaliseOverview(value: unknown): Overview {
  const row = asRow(value);
  return {
    title: text(row.title),
    type: canonicalIncidentType(row.type),
    severity_level: severity(row.severity_level),
    description: text(row.description),
    location: text(row.location),
  };
}

/**
 * A stored payload -> the envelope. Cameras without a video name are dropped and a repeated name keeps its first
 * report. A payload that is not an envelope (no `cameras` array) gives no cameras and an overview read from the
 * payload's `overview`, so callers see "nothing to show" rather than an exception.
 */
export function parseEnvelope(payload: unknown): ReportEnvelope {
  const row = asRow(payload);
  const seen = new Set<string>();
  const cameras: Camera[] = [];
  for (const raw of Array.isArray(row.cameras) ? row.cameras : []) {
    const camera = asRow(raw);
    const video = text(camera.video);
    if (!video || seen.has(video)) continue;
    seen.add(video);
    cameras.push({ video, report: asRow(camera.report) });
  }
  return { overview: normaliseOverview(row.overview), cameras };
}

/** The stored shape of an envelope: what a revision's payload column holds. */
export function envelopePayload(envelope: ReportEnvelope): ReportPayload {
  return {
    overview: { ...envelope.overview },
    cameras: envelope.cameras.map((camera) => ({ video: camera.video, report: camera.report })),
  };
}

/** The video names an envelope has a camera for, in order. */
export const cameraNames = (envelope: ReportEnvelope): string[] => envelope.cameras.map((camera) => camera.video);

/**
 * One camera's report when it passes validation policy core-scored-v1, the level analyses are accepted and stored
 * with (timeline enrichment violations are allowed); null when the camera is absent or its report fails that policy
 * (so a caller never feeds an invalid report to the report panes). A stored analysis carries the derived
 * incident.duration the schema forbids from the model, so the copy validated is the model-shaped part; the report
 * returned is the stored one, unchanged.
 */
export function cameraReport(envelope: ReportEnvelope, video: string): ReportPayload | null {
  const camera = envelope.cameras.find((candidate) => candidate.video === video);
  if (!camera) return null;
  try {
    validateCore(withoutDerivedFields(camera.report));
    return camera.report;
  } catch {
    return null;
  }
}

/** The first camera (in order) whose report is contract-valid among `preferred` names, else among all cameras. */
export function firstValidCamera(envelope: ReportEnvelope, preferred?: readonly string[]): string | null {
  const pool = preferred ? envelope.cameras.filter((camera) => preferred.includes(camera.video)) : envelope.cameras;
  return pool.find((camera) => cameraReport(envelope, camera.video) !== null)?.video ?? null;
}

/** The envelope with one camera's report replaced. Throws when the envelope has no such camera. */
export function replaceCameraReport(envelope: ReportEnvelope, video: string, report: ReportPayload): ReportEnvelope {
  if (!envelope.cameras.some((camera) => camera.video === video)) throw new Error(`The report has no camera for ${video}.`);
  return { ...envelope, cameras: envelope.cameras.map((camera) => (camera.video === video ? { ...camera, report } : camera)) };
}

/** The envelope with its overview replaced by the edited fields (normalised). Cameras are untouched. */
export function replaceOverview(envelope: ReportEnvelope, overview: Partial<Overview>): ReportEnvelope {
  return { ...envelope, overview: normaliseOverview(overview) };
}

export type CoverageVerdict =
  | { status: 'complete' }
  | { status: 'lacks'; missing: string[] }
  | { status: 'removed'; removed: string[] }
  | { status: 'lacks-and-removed'; missing: string[]; removed: string[] };

/**
 * Coverage of a revision: `covered` is its stored video_names, `current` the incident's videos now. Current videos not
 * covered are missing ("Does not include"); covered names no longer current were removed ("Includes a removed video").
 * Names are compared exactly (they are real file names) and listed in input order without repeats.
 */
export function coverageVerdict(covered: readonly string[], current: readonly string[]): CoverageVerdict {
  const unique = (names: readonly string[]) => [...new Set(names)];
  const coveredSet = new Set(covered);
  const currentSet = new Set(current);
  const missing = unique(current).filter((name) => !coveredSet.has(name));
  const removed = unique(covered).filter((name) => !currentSet.has(name));
  if (missing.length && removed.length) return { status: 'lacks-and-removed', missing, removed };
  if (missing.length) return { status: 'lacks', missing };
  if (removed.length) return { status: 'removed', removed };
  return { status: 'complete' };
}

/** The coverage note shown beside a version; null when the version is complete. */
export function coverageNote(verdict: CoverageVerdict): string | null {
  const parts: string[] = [];
  if (verdict.status === 'lacks' || verdict.status === 'lacks-and-removed') parts.push(`Does not include: ${verdict.missing.join(', ')}`);
  if (verdict.status === 'removed' || verdict.status === 'lacks-and-removed')
    parts.push(`Includes a removed video: ${verdict.removed.join(', ')}`);
  return parts.length ? parts.join('. ') : null;
}
