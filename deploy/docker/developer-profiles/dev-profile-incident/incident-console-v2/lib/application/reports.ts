// SPDX-License-Identifier: Apache-2.0

// Report use cases: what a route asks for, in domain terms. They depend on
// ports only; storage signing is passed in as a function, so they never import
// an adapter, R2 or PostgREST and are tested with in-memory fakes.

import type { IncidentRepository, ReviewState, RunKey } from '@/lib/ports';
import type { ReportView } from '@/lib/reports/report-view';
import type { ReviewStatus } from '@/lib/reports/storage';
import { toReportView } from '@/lib/reports/view';

/** Turns a stored object key into a short-lived URL the browser can play. */
export type SignStorageKey = (storageKey: string) => Promise<string>;

/** One run's report view; null when the run, its video or its incident is missing. */
export async function getReport(incidents: IncidentRepository, key: RunKey, sign: SignStorageKey): Promise<ReportView | null> {
  const record = await incidents.getRunReport(key);
  if (!record) return null;
  if (!record.video.storageKey) throw new Error('The report has no linked R2 video');
  return toReportView(record, await sign(record.video.storageKey));
}

/**
 * The review transition rule: null when the status is unchanged; otherwise the
 * reviewer becomes the editor, and the verifier only when verifying.
 */
export function nextReviewState(current: ReviewState | null, status: ReviewStatus, reviewer: string, now: string): ReviewState | null {
  if (current?.status === status) return null;
  const verified = status === 'verified';
  return { status, editedBy: reviewer, editedAt: now, verifiedBy: verified ? reviewer : null, verifiedAt: verified ? now : null };
}

export type ReviewChange = { kind: 'not-found' } | { kind: 'unchanged' } | { kind: 'changed'; at: string };

export async function changeReviewStatus(
  incidents: IncidentRepository,
  key: RunKey,
  status: ReviewStatus,
  reviewer: string,
  clock: () => Date = () => new Date(),
): Promise<ReviewChange> {
  const [exists, current] = await Promise.all([incidents.runExists(key), incidents.getReview(key)]);
  if (!exists) return { kind: 'not-found' };
  const now = clock().toISOString();
  const next = nextReviewState(current, status, reviewer, now);
  if (!next) return { kind: 'unchanged' };
  await incidents.saveReview(key, next);
  return { kind: 'changed', at: now };
}
