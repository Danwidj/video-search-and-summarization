// SPDX-License-Identifier: Apache-2.0

// Report use cases: what a route asks for, in domain terms. They depend on
// ports only; R2 signing and deletion are passed in as functions, so they never
// import an adapter, R2 or PostgREST and are tested with in-memory fakes.

import type { DbAdapters, IncidentRepository, ReviewState, RunKey } from '@/lib/ports';
import type { ReportView } from '@/lib/reports/report-view';
import type { ReviewStatus } from '@/lib/reports/storage';
import { toReportView } from '@/lib/reports/view';

/** Turns a stored object key into a short-lived URL the browser can play. */
export type SignStorageKey = (storageKey: string) => Promise<string>;

/** Deletes a stored video object and everything derived from it (its thumbnail). */
export type RemoveStoredVideo = (storageKey: string) => Promise<unknown>;

/** One run's report view; null when the run, its video or its incident is missing. */
export async function getReport(incidents: IncidentRepository, key: RunKey, sign: SignStorageKey): Promise<ReportView | null> {
  const record = await incidents.getRunReport(key);
  if (!record) return null;
  if (!record.video.storageKey) throw new Error('The report has no linked R2 video');
  return toReportView(record, await sign(record.video.storageKey));
}

/**
 * The review transition rule (set_review_status applies it in the database;
 * the in-memory fake models it with this function): null when the status is
 * unchanged, a run without a review counting as 'unreviewed'; otherwise the
 * reviewer becomes the verifier only when verifying. The edit stamps are kept:
 * they mean "last content edit", and a status change is not one.
 */
export function nextReviewState(current: ReviewState | null, status: ReviewStatus, reviewer: string, now: string): ReviewState | null {
  if ((current?.status ?? 'unreviewed') === status) return null;
  const verified = status === 'verified';
  return {
    status,
    editedBy: current?.editedBy ?? null,
    editedAt: current?.editedAt ?? null,
    verifiedBy: verified ? reviewer : null,
    verifiedAt: verified ? now : null,
  };
}

export type ReviewChange = { kind: 'not-found' } | { kind: 'unchanged' } | { kind: 'changed'; at: string };

/** One atomic transition; `at` is the stored verification time when verifying, else the time of the request. */
export async function changeReviewStatus(
  incidents: IncidentRepository,
  key: RunKey,
  status: ReviewStatus,
  reviewer: string,
  clock: () => Date = () => new Date(),
): Promise<ReviewChange> {
  if (!(await incidents.runExists(key))) return { kind: 'not-found' };
  const transition = await incidents.setReviewStatus(key, status, reviewer);
  if (!transition.changed) return { kind: 'unchanged' };
  return { kind: 'changed', at: transition.verifiedAt ?? clock().toISOString() };
}

/**
 * Deletes one run's report, or the whole video: its stored objects first, then
 * the video row (incidents, evidence, reviews and reports cascade) and the run
 * records that name only this video.
 */
export async function deleteReport(
  { incidents, videos }: DbAdapters,
  key: RunKey,
  wholeVideo: boolean,
  removeStoredVideo: RemoveStoredVideo,
): Promise<void> {
  if (!wholeVideo) {
    await incidents.deleteRun(key);
    return;
  }
  const video = await videos.getVideo(key.videoId);
  if (video?.storageKey == null) throw new Error('Video has no R2 object key');
  await removeStoredVideo(video.storageKey);
  await videos.deleteVideo(key.videoId);
}
