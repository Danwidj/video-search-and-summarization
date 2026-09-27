// SPDX-License-Identifier: Apache-2.0

// Builds a video's analysis history (server-side) from two sources:
// - runs with an incident for this video (incidents.incident_id = videoId),
//   which is how successful console, agent, eval and seed runs link to videos;
// - attempt records with no incident whose model_runs.notes explicitly name
//   this videoId (failed attempts, and successful runs whose report was later
//   deleted). The notes text search is only a pre-filter; every candidate is
//   confirmed from its parsed notes.
// Run counts are always per outcome; nothing treats a model_runs row as a
// successful analysis by default.

import { explicitVideoId, parseRunNotes } from '@/lib/reports/run-notes';
import type { OutcomeCounts, RunHistoryEntry } from '@/lib/runs/types';
import { canonicalIncidentType } from '@/lib/reports/normalize';

type Row = Record<string, unknown>;

const text = (value: unknown): string | null => (typeof value === 'string' && value.trim() ? value : null);
const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const first = (value: unknown): Row | null => (Array.isArray(value) ? ((value[0] as Row) ?? null) : value && typeof value === 'object' ? (value as Row) : null);

export interface HistoryInputs {
  videoId: string;
  /** incidents rows for the video with embedded model_runs, reports and review_status. */
  incidentRows: Row[];
  /** model_runs rows whose notes mention the videoId (pre-filter). */
  attemptCandidates: Row[];
  /** Model runs shared by more than one video (batch eval/seed runs). */
  sharedRunIds: Set<string>;
}

function fromNotes(entry: RunHistoryEntry, notes: unknown): RunHistoryEntry {
  const parsed = parseRunNotes(notes);
  if (parsed.kind === 'contract') {
    return {
      ...entry,
      outcome: parsed.status,
      outcomeInferred: parsed.statusInferred,
      source: 'console',
      attemptedAt: parsed.attemptedAt ?? entry.attemptedAt,
      additionalInstruction: parsed.request.additionalInstruction ?? null,
      repair: parsed.status === 'valid_after_structural_repair' && parsed.repair
        ? { ruleSet: String(parsed.repair.ruleSet ?? ''), operations: Array.isArray(parsed.repair.operations) ? (parsed.repair.operations as Array<Record<string, unknown>>) : [] }
        : null,
      enrichmentIssues: [...new Set(parsed.enrichment.map((violation) => violation.code))],
    };
  }
  if (parsed.kind === 'failed-attempt') {
    const violations = parsed.validation.firstPass.map((violation) => ({ code: violation.code, message: violation.message }));
    const revalidation = parsed.repair && Array.isArray(parsed.repair.revalidation) ? (parsed.repair.revalidation as Array<{ code: string; message: string }>) : [];
    return {
      ...entry,
      outcome: parsed.status,
      outcomeInferred: false,
      source: 'console',
      attemptedAt: parsed.attemptedAt ?? entry.attemptedAt,
      additionalInstruction: parsed.request.additionalInstruction ?? null,
      failure: {
        stage: parsed.stage,
        code: parsed.failure?.code ?? parsed.status,
        message: parsed.failure?.message ?? '',
        violations: [...violations, ...revalidation.map((violation) => ({ code: violation.code, message: violation.message }))],
      },
    };
  }
  // Legacy console notes, unverifiable contract records, eval/seed notes or
  // no notes: a successful earlier analysis whose outcome was not recorded.
  return { ...entry, outcome: 'legacy', outcomeInferred: true, source: parsed.kind === 'legacy' ? 'console' : entry.source };
}


export function buildRunHistory(inputs: HistoryInputs): { runs: RunHistoryEntry[]; counts: OutcomeCounts } {
  const runs: RunHistoryEntry[] = [];
  const seen = new Set<string>();

  for (const row of inputs.incidentRows) {
    const runId = text(row.model_run_id);
    if (!runId || seen.has(runId)) continue;
    seen.add(runId);
    const modelRun = first(row.model_runs) ?? {};
    const reportRow = first(row.reports);
    const base: RunHistoryEntry = {
      modelRunId: runId,
      model: text(modelRun.model_name) ?? 'Unknown model',
      attemptedAt: text(reportRow?.generated_datetime) ?? text(modelRun.run_datetime),
      outcome: 'legacy',
      outcomeInferred: true,
      source: inputs.sharedRunIds.has(runId) ? 'shared' : 'other',
      report: reportRow && text(reportRow.id)
        ? { reportId: text(reportRow.id)!, type: canonicalIncidentType(row.type), severityLevel: num(row.severity_level) }
        : null,
      reportRemoved: false,
      additionalInstruction: null,
      failure: null,
      repair: null,
    };
    const entry = fromNotes(base, modelRun.notes);
    // A successful analysis keeps its outcome; a report only exists when a reports row does.
    runs.push(entry.outcome === 'contract_failed' || entry.outcome === 'request_failed' ? { ...entry, report: null } : entry);
  }

  for (const candidate of inputs.attemptCandidates) {
    const runId = text(candidate.id);
    if (!runId || seen.has(runId) || explicitVideoId(candidate.notes) !== inputs.videoId) continue;
    seen.add(runId);
    const base: RunHistoryEntry = {
      modelRunId: runId,
      model: text(candidate.model_name) ?? 'Unknown model',
      attemptedAt: text(candidate.run_datetime),
      outcome: 'legacy',
      outcomeInferred: true,
      source: 'other',
      report: null,
      reportRemoved: false,
      additionalInstruction: null,
      failure: null,
      repair: null,
    };
    const entry = fromNotes(base, candidate.notes);
    const failed = entry.outcome === 'contract_failed' || entry.outcome === 'request_failed';
    runs.push({ ...entry, report: null, reportRemoved: !failed });
  }

  runs.sort((a, b) => (b.attemptedAt ?? '').localeCompare(a.attemptedAt ?? '') || a.modelRunId.localeCompare(b.modelRunId));
  const counts: OutcomeCounts = { attempts: runs.length, withReport: 0, valid_first_pass: 0, valid_after_structural_repair: 0, contract_failed: 0, request_failed: 0, legacy: 0 };
  for (const run of runs) {
    counts[run.outcome] += 1;
    if (run.report) counts.withReport += 1;
  }
  return { runs, counts };
}
