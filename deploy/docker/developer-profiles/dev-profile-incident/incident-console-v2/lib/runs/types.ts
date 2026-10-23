// SPDX-License-Identifier: Apache-2.0

// Browser-safe shapes for a video's analysis history. A video is the parent;
// each history entry is one analysis of that video (a video/model-run pair).
// Successful analyses may have a report; failed attempts never do.

import type { RunOutcome } from '@/lib/runs/labels';

export interface RunHistoryEntry {
  modelRunId: string;
  model: string;
  /** When the analysis was attempted (UTC string; render with lib/time.ts). */
  attemptedAt: string | null;
  outcome: RunOutcome;
  /** True when the outcome was inferred because the run predates recorded outcomes. */
  outcomeInferred: boolean;
  /** 'console' = recorded by this console; 'shared' = a batch run (eval/seed) covering many videos; 'other' = anything else. */
  source: 'console' | 'shared' | 'other';
  /** The run's AI report revision; null for a failed attempt. */
  revision: { revisionId: number; type: string | null; severityLevel: number | null } | null;
  additionalInstruction: string | null;
  failure: { stage: string | null; code: string; message: string; violations: Array<{ code: string; message: string }> } | null;
  repair: { ruleSet: string; operations: Array<Record<string, unknown>> } | null;
  /** Successful runs: problems confined to unscored model fields (e.g. the timeline); they do not affect validity. */
  enrichmentIssues?: string[];
  /** The run's AI revision is the incident's official revision. */
  isOfficial?: boolean;
}

export interface OutcomeCounts {
  /** Every analysis in the history, whatever its outcome. */
  attempts: number;
  /** Analyses that have an AI report revision. */
  withReport: number;
  valid_first_pass: number;
  valid_after_structural_repair: number;
  contract_failed: number;
  request_failed: number;
  legacy: number;
}

export interface VideoRunHistory {
  video: { videoId: string; filename: string; uploadedAt: string | null; source: string | null; playbackUrl: string | null };
  runs: RunHistoryEntry[];
  counts: OutcomeCounts;
  /** The incident's official revision (any kind), if one is marked. */
  officialRevisionId: number | null;
}
