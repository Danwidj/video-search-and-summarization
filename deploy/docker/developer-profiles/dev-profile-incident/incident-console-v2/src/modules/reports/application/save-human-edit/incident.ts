// SPDX-License-Identifier: Apache-2.0

// Save human edit on an incident: one camera's structured edit, or the overview, saved as a new human revision
// of the whole envelope. The new revision takes its parent's coverage (the store copies it). When the incident
// has no official revision the new revision is the searchable one, so its crops are embedded first and written
// in the same call as the revision: a failed embedding writes nothing.

import { missingItemFields } from '@/modules/contract/domain/validate';
import { incidentCrops } from '@/modules/reports/application/incident-crops';
import { SearchableStepError } from '@/modules/reports/application/save-human-edit';
import type { EmbedEvidence } from '@/modules/reports/application/types';
import { isCameraEvidence } from '@/modules/reports/domain/camera-evidence';
import type { StructuredEdit } from '@/modules/reports/domain/edit-draft';
import {
  envelopePayload,
  replaceCameraReport,
  replaceOverview,
  type Overview,
  type ReportEnvelope,
} from '@/modules/reports/domain/envelope';
import type {
  IncidentId,
  IncidentReportRepository,
  IncidentRevisionRecord,
  IncidentRevisionSummary,
} from '@/modules/reports/domain/IncidentReportRepository';
import { humanRevisionContent, isEvidenceKeyOfVideo, type EvidenceEntry } from '@/modules/reports/domain/revision';
import { StoreRejection } from '@/modules/shared/domain/common';

export type IncidentEditTarget = { camera: string; edit: StructuredEdit } | { overview: Partial<Overview> };

export interface IncidentEditInput {
  incidentId: IncidentId;
  parentId: number;
  target: IncidentEditTarget;
  createdBy: string;
  note?: string | null;
}

/** An edit's item images must be ones the opened revision already used or new uploads for this camera's video. */
function checkImages(parent: IncidentRevisionRecord, edit: StructuredEdit, videoKey: string | null) {
  const known = new Set(parent.evidence.flatMap((entry) => (entry.image ? [entry.image] : [])));
  for (const item of [...edit.entities, ...edit.instruments, ...edit.assets]) {
    if (item.image && !known.has(item.image) && !(videoKey !== null && isEvidenceKeyOfVideo(item.image, videoKey))) {
      throw new StoreRejection('invalid', `An evidence image is not one of this video's images: ${item.image}`);
    }
  }
}

/** The envelope and evidence after the edit, with the edited camera's own evidence rebuilt and the others kept. */
function editedContent(
  parent: IncidentRevisionRecord,
  target: IncidentEditTarget,
  videoKey: string | null,
): { envelope: ReportEnvelope; evidence: EvidenceEntry[] } {
  if ('overview' in target) return { envelope: replaceOverview(parent.envelope, target.overview), evidence: parent.evidence };
  const camera = parent.envelope.cameras.find((candidate) => candidate.video === target.camera);
  if (!camera) throw new StoreRejection('not-found', `The revision has no camera for ${target.camera}`);
  const mine = parent.evidence.filter((entry) => isCameraEvidence(entry, target.camera, videoKey));
  const others = parent.evidence.filter((entry) => !isCameraEvidence(entry, target.camera, videoKey));
  const content = humanRevisionContent({ payload: camera.report, evidence: mine }, target.edit);
  const missing = missingItemFields(content.payload);
  if (missing.length) {
    throw new StoreRejection(
      'invalid',
      `The saved report would not satisfy incident-contract-v4: ${missing.map((v) => v.message).join('; ')}`,
    );
  }
  return {
    envelope: replaceCameraReport(parent.envelope, target.camera, content.payload),
    evidence: [...others, ...content.evidence.map((entry) => ({ ...entry, video: target.camera }))],
  };
}

/** Save: a new human revision from one edit, with the revision the reviewer opened as its parent. Earlier revisions are never changed. */
export async function saveIncidentHumanEdit(
  incidentReports: Pick<IncidentReportRepository, 'getIncident' | 'getRevision' | 'saveHumanRevision'>,
  input: IncidentEditInput,
  embed: EmbedEvidence,
): Promise<IncidentRevisionSummary> {
  const incident = await incidentReports.getIncident(input.incidentId);
  if (!incident) throw new StoreRejection('not-found', `Incident not found: ${input.incidentId}`);
  const parent = await incidentReports.getRevision(input.incidentId, input.parentId);
  if (!parent || parent.revision.revisionId !== input.parentId) {
    throw new StoreRejection('not-found', `Revision not found for this incident: ${input.parentId}`);
  }
  let videoKey: string | null = null;
  if ('camera' in input.target) {
    const name = input.target.camera;
    if (!parent.revision.videoNames.includes(name)) {
      throw new StoreRejection('invalid', `${name} is not covered by revision ${input.parentId}`);
    }
    const video = incident.videos.find((candidate) => candidate.videoId === name);
    if (!video) throw new StoreRejection('not-found', `Video not found in this incident: ${name}`);
    videoKey = video.storageKey;
    checkImages(parent, input.target.edit, videoKey);
  }
  const { envelope, evidence } = editedContent(parent, input.target, videoKey);
  let crops: Awaited<ReturnType<typeof incidentCrops>> = [];
  if (incident.officialRevisionId === null) {
    try {
      crops = await incidentCrops(envelope, evidence, parent.revision.videoNames, incident.videos, embed);
    } catch (error) {
      throw new SearchableStepError(error instanceof Error ? error.message : String(error));
    }
  }
  return incidentReports.saveHumanRevision({
    incidentId: input.incidentId,
    parentId: input.parentId,
    payload: envelopePayload(envelope),
    evidence,
    crops,
    createdBy: input.createdBy,
    note: input.note?.trim() || null,
  });
}
