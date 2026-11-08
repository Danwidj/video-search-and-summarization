// SPDX-License-Identifier: Apache-2.0

// The one way a use case gets vectors for a revision's searchable crops: it embeds the text each crop row will store
// (evidenceSearchTexts), so the card and the vector say the same thing, and it asks for nothing when no item has text.

import { evidenceSearchTexts, type EvidenceEmbedding, type EvidenceEntry, type ReportPayload } from '@/modules/reports/domain/revision';
import type { EmbedEvidence } from '@/modules/reports/application/types';

/** Embeds the searchable texts of a revision's evidence; no call when there is nothing to embed. */
export async function embedSearchableEvidence(
  payload: ReportPayload,
  evidence: EvidenceEntry[],
  embed: EmbedEvidence,
): Promise<EvidenceEmbedding[]> {
  const texts = evidenceSearchTexts(payload, evidence);
  return texts.length ? embed(texts) : [];
}
