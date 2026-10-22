// SPDX-License-Identifier: Apache-2.0

// A video's analysis history in display order, with its counts. Run counts are
// always per outcome: a failed attempt is an attempt, never a report.

import type { OutcomeCounts, RunHistoryEntry } from '@/lib/runs/types';

/** Newest first (ties by run id), and the per-outcome counts. */
export function summarizeRuns(entries: RunHistoryEntry[]): { runs: RunHistoryEntry[]; counts: OutcomeCounts } {
  const runs = [...entries].sort((a, b) => (b.attemptedAt ?? '').localeCompare(a.attemptedAt ?? '') || a.modelRunId.localeCompare(b.modelRunId));
  const counts: OutcomeCounts = { attempts: runs.length, withReport: 0, valid_first_pass: 0, valid_after_structural_repair: 0, contract_failed: 0, request_failed: 0, legacy: 0 };
  for (const run of runs) {
    counts[run.outcome] += 1;
    if (run.report) counts.withReport += 1;
  }
  return { runs, counts };
}
