// SPDX-License-Identifier: Apache-2.0

// Report use cases: what a route asks for, in domain terms. They depend on
// ports only; R2 signing, R2 deletion and the agent's embedding call are
// passed in as functions, so they never import an adapter, R2 or PostgREST and
// are tested with in-memory fakes.

import type { DbAdapters, IncidentRepository, OfficialChange, RevisionRecord, VideoRepository } from '@/lib/ports';
import { StoreRejection } from '@/lib/ports';
import type { StructuredEdit } from '@/lib/reports/edit-draft';
import type { ReportView } from '@/lib/reports/report-view';
import { humanRevisionContent, isEvidenceKeyOfVideo, officialCrops, type EvidenceEmbedding, type RevisionSummary } from '@/lib/reports/revision';
import { toReportView } from '@/lib/reports/view';

/** Turns a stored object key into a short-lived URL the browser can play or show. */
export type SignStorageKey = (storageKey: string) => Promise<string>;

/** Deletes a stored video object and everything derived from it (its thumbnail). */
export type RemoveStoredVideo = (storageKey: string) => Promise<unknown>;

/** The agent's embeddings for the evidence of one stored revision. */
export type EmbedRevisionEvidence = (revisionId: number) => Promise<EvidenceEmbedding[]>;

/** Signs each item's image so the browser can show it; an image that cannot be signed is shown as missing. */
async function withImageUrls(view: ReportView, sign: SignStorageKey): Promise<ReportView> {
  const signed = new Map<string, string | null>();
  const urlOf = async (image: string | null) => {
    if (!image) return null;
    if (!signed.has(image)) signed.set(image, await sign(image).catch(() => null));
    return signed.get(image) ?? null;
  };
  const items = [...view.structured.entities, ...view.structured.instruments, ...view.structured.assets];
  await Promise.all(items.map(async (item) => {
    if (item.evidence) item.evidence = { ...item.evidence, imageUrl: await urlOf(item.evidence.image) };
  }));
  return view;
}

/** One revision's report view (revisionId null: the official revision, else the newest); null when the video or revision is missing. */
export async function getReport(incidents: IncidentRepository, videoId: string, revisionId: number | null, sign: SignStorageKey): Promise<ReportView | null> {
  const record = await incidents.getRevision(videoId, revisionId);
  if (!record) return null;
  if (!record.video.storageKey) throw new Error('The report has no linked R2 video');
  return withImageUrls(toReportView(record, await sign(record.video.storageKey)), sign);
}

/** The incident's History: every revision, newest first. */
export function listRevisions(incidents: IncidentRepository, videoId: string): Promise<RevisionSummary[]> {
  return incidents.listRevisions(videoId);
}

/** An edit's item images must be ones the opened revision already used or new uploads for this video. */
function checkImages(parent: RevisionRecord, edit: StructuredEdit) {
  const known = new Set(parent.evidence.flatMap((entry) => (entry.image ? [entry.image] : [])));
  for (const item of [...edit.entities, ...edit.instruments, ...edit.assets]) {
    if (item.image && !known.has(item.image) && !isEvidenceKeyOfVideo(item.image, parent.revision.videoId)) {
      throw new StoreRejection('invalid', `An evidence image is not one of this video's images: ${item.image}`);
    }
  }
}

/**
 * Save: a new human revision from the form's edit, with the revision the
 * reviewer opened as its parent. Earlier revisions are never changed.
 */
export async function saveHumanEdit(
  incidents: IncidentRepository,
  input: { videoId: string; parentId: number; edit: StructuredEdit; createdBy: string; note?: string | null },
): Promise<RevisionSummary> {
  const parent = await incidents.getRevision(input.videoId, input.parentId);
  if (!parent) throw new StoreRejection('not-found', `Revision not found for this video: ${input.parentId}`);
  checkImages(parent, input.edit);
  const { payload, evidence } = humanRevisionContent(parent, input.edit);
  return incidents.saveHumanRevision({ videoId: input.videoId, parentId: input.parentId, payload, evidence, createdBy: input.createdBy, note: input.note?.trim() || null });
}

/**
 * Marks a revision official (revisionId null clears it). Marking asks the
 * agent to embed the revision's evidence images and hands the vectors to the
 * store, which rebuilds the incident's evidence_crops in one transaction; a
 * failure leaves the previous official revision and crops untouched.
 */
export async function setOfficialRevision(
  { incidents, videos }: Pick<DbAdapters, 'incidents' | 'videos'>,
  videoId: string,
  revisionId: number | null,
  embed: EmbedRevisionEvidence,
): Promise<OfficialChange> {
  if (revisionId === null) return videos.setOfficialRevision(videoId, null, []);
  const record = await incidents.getRevision(videoId, revisionId);
  if (!record) throw new StoreRejection('not-found', `Revision not found for this video: ${revisionId}`);
  const embeddings = record.evidence.some((entry) => entry.image) ? await embed(revisionId) : [];
  return videos.setOfficialRevision(videoId, revisionId, officialCrops(record.payload, record.evidence, embeddings));
}

/** What storing a new revision's crops did: the rows stored, or null when skipped or failed (error says why). */
export interface SearchableCropsResult {
  crops: number | null;
  error?: string;
}

/**
 * After a new revision is saved: when it is now the video's searchable
 * revision (the video has no official revision, so the newest is searched),
 * embeds its images and stores its evidence_crops, so Find evidence returns
 * the video before anyone marks a revision official. With an official
 * revision nothing changes. The revision is already saved, so a failure here
 * is returned, never thrown: the crops can be rebuilt by marking it official.
 */
export async function storeSearchableCrops(
  { incidents, videos }: Pick<DbAdapters, 'incidents' | 'videos'>,
  videoId: string,
  revisionId: number,
  embed: EmbedRevisionEvidence,
): Promise<SearchableCropsResult> {
  try {
    const video = await videos.getVideo(videoId);
    if (!video || video.officialRevisionId !== null) return { crops: null };
    const record = await incidents.getRevision(videoId, revisionId);
    if (!record) return { crops: null };
    const embeddings = record.evidence.some((entry) => entry.image) ? await embed(revisionId) : [];
    return { crops: (await videos.setRevisionCrops(videoId, revisionId, officialCrops(record.payload, record.evidence, embeddings))).crops };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`Could not store the evidence crops of revision ${revisionId} of ${videoId}: ${message}`);
    return { crops: null, error: message };
  }
}

/**
 * Deletes the whole video: its stored objects first, then the video row
 * (revisions, evidence crops and query results cascade) and the run records
 * that name only this video. Revisions are append-only, so there is no
 * deleting a single one. Evidence images under evidence/<videoId>/ are left in R2.
 */
export async function deleteVideoAndReports(
  videos: VideoRepository,
  videoId: string,
  removeStoredVideo: RemoveStoredVideo,
): Promise<void> {
  const video = await videos.getVideo(videoId);
  if (video?.storageKey == null) throw new Error('Video has no R2 object key');
  await removeStoredVideo(video.storageKey);
  await videos.deleteVideo(videoId);
}
