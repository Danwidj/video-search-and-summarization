// SPDX-License-Identifier: Apache-2.0

// Get report: one revision of an incident for the report page. It carries the
// overview, the coverage verdict, the cameras and the chosen camera's report
// (in the shape the report panes read) with its video and evidence images
// signed for the browser.

import { cameraReport, firstValidCamera } from '@/modules/reports/domain/envelope';
import { cameraEvidenceItems, type IncidentEvidenceItem } from '@/modules/reports/domain/incident-evidence';
import type { IncidentId, IncidentReportRepository } from '@/modules/reports/domain/IncidentReportRepository';
import type { ReportView } from '@/modules/reports/domain/report-view';
import { coverageView, toCameraReportView } from '@/modules/reports/application/report-view';
import type { CameraView, IncidentReportView, SignStorageKey } from '@/modules/reports/application/types';
import { StoreRejection } from '@/modules/shared/domain/common';

/** Signs each item's image so the browser can show it; an image that cannot be signed is shown as missing. */
async function withImageUrls(view: ReportView, sign: SignStorageKey): Promise<ReportView> {
  const signed = new Map<string, string | null>();
  const urlOf = async (image: string | null) => {
    if (!image) return null;
    if (!signed.has(image)) signed.set(image, await sign(image).catch(() => null));
    return signed.get(image) ?? null;
  };
  const items = [...view.structured.entities, ...view.structured.instruments, ...view.structured.assets];
  await Promise.all(
    items.map(async (item) => {
      if (item.evidence) {
        const [imageUrl, frameUrl] = await Promise.all([urlOf(item.evidence.image), urlOf(item.evidence.frame)]);
        item.evidence = { ...item.evidence, imageUrl, frameUrl };
      }
    }),
  );
  return view;
}

/**
 * One revision of the incident (revisionId null: the official revision, else the newest) and one of its cameras
 * (camera null: the first contract-valid camera still in the incident, else the first valid one). Null when the
 * incident or revision is missing. A camera that is an incident video but not in the revision falls back to the first valid camera (its chip stays
 * disabled as "not in this version"). Throws StoreRejection 'not-found' for a camera the incident does not have. The view
 * also lists the incident's videos, so the page counts the incident rather than the open version.
 * A camera whose video was removed shows its report without a player; one whose report is not contract-valid
 * is listed but never shown. `evidence` lists the items of every valid camera, whichever one is chosen.
 */
export async function getReport(
  incidentReports: IncidentReportRepository,
  incidentId: IncidentId,
  revisionId: number | null,
  camera: string | null,
  sign: SignStorageKey,
): Promise<IncidentReportView | null> {
  const incident = await incidentReports.getIncident(incidentId);
  if (!incident) return null;
  const record = await incidentReports.getRevision(incidentId, revisionId);
  if (!record) return null;

  const { envelope } = record;
  const current = new Set(incident.videos.map((video) => video.videoId));
  const inVersion = new Set(envelope.cameras.map((entry) => entry.video));
  const autoJoinOf = new Map(incident.videos.map((video) => [video.videoId, video.autoJoin]));
  // An incident video the version does not cover (added by an accept or merge since) is listed so the page counts it, but it has no report.
  const cameras: CameraView[] = [
    ...envelope.cameras.map((entry) => ({
      video: entry.video,
      current: current.has(entry.video),
      inVersion: true,
      valid: cameraReport(envelope, entry.video) !== null,
      autoJoin: autoJoinOf.get(entry.video) ?? null,
    })),
    ...incident.videos
      .filter((video) => !inVersion.has(video.videoId))
      .map((video) => ({ video: video.videoId, current: true, inVersion: false, valid: false, autoJoin: video.autoJoin })),
  ];
  let chosen: string | null;
  if (camera !== null) {
    if (!inVersion.has(camera) && !current.has(camera)) throw new StoreRejection('not-found', `The revision has no camera for ${camera}`);
    if (inVersion.has(camera)) chosen = cameraReport(envelope, camera) === null ? null : camera;
    else chosen = firstValidCamera(envelope, [...current]) ?? firstValidCamera(envelope);
  } else chosen = firstValidCamera(envelope, [...current]) ?? firstValidCamera(envelope);

  let report: ReportView | null = null;
  const entry = envelope.cameras.find((candidate) => candidate.video === chosen);
  if (entry) {
    const key = incident.videos.find((video) => video.videoId === entry.video)?.storageKey;
    const playbackUrl = key ? await sign(key) : '';
    report = await withImageUrls(toCameraReportView(record, entry, incident, playbackUrl), sign);
  }
  // Every valid camera's evidence, not just the chosen one's: the list reads the whole version.
  const evidence: IncidentEvidenceItem[] = [];
  for (const camera of envelope.cameras) {
    if (cameraReport(envelope, camera.video) === null) continue;
    const view =
      camera.video === entry?.video && report ? report : await withImageUrls(toCameraReportView(record, camera, incident, ''), sign);
    evidence.push(...cameraEvidenceItems(camera.video, current.has(camera.video), view.structured));
  }
  return {
    incidentId,
    revision: record.revision,
    overview: envelope.overview,
    coverage: coverageView(record.revision, incident),
    cameras,
    incidentVideos: incident.videos.map((video) => video.videoId),
    camera: camera !== null && inVersion.has(camera) ? camera : (entry?.video ?? null),
    report,
    evidence,
    officialRevisionId: incident.officialRevisionId,
    officialSince: incident.officialSince,
  };
}
