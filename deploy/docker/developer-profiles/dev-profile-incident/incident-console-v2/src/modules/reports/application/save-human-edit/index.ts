// SPDX-License-Identifier: Apache-2.0

// Save human edit: a new human revision from the form's edit, parented on the
// revision the reviewer opened.

import type { IncidentRepository, RevisionRecord } from '@/modules/reports/domain/IncidentRepository';
import type { StructuredEdit } from '@/modules/reports/domain/edit-draft';
import { StoreRejection } from '@/modules/shared/domain/common';
import { missingItemFields } from '@/modules/contract/domain/validate';
import { humanRevisionContent, isEvidenceKeyOfVideo, type RevisionSummary } from '@/modules/reports/domain/revision';

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
  const missing = missingItemFields(payload);
  if (missing.length) throw new StoreRejection('invalid', `The saved report would not satisfy incident-contract-v4: ${missing.map((v) => v.message).join('; ')}`);
  return incidents.saveHumanRevision({ videoId: input.videoId, parentId: input.parentId, payload, evidence, createdBy: input.createdBy, note: input.note?.trim() || null });
}
