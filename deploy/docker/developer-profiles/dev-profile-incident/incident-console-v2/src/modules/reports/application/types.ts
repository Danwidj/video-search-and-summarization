// SPDX-License-Identifier: Apache-2.0

// Function types the report use cases take from their caller. The caller
// supplies R2 signing, R2 deletion and the agent's embedding call, so no use
// case imports an adapter.

import type { EvidenceEmbedding } from '@/modules/reports/domain/revision';

/** Turns a stored object key into a short-lived URL the browser can play or show. */
export type SignStorageKey = (storageKey: string) => Promise<string>;

/** Deletes a stored video object and everything derived from it (its thumbnail). */
export type RemoveStoredVideo = (storageKey: string) => Promise<unknown>;

/** The agent's embeddings for the evidence of one stored revision. */
export type EmbedRevisionEvidence = (revisionId: number) => Promise<EvidenceEmbedding[]>;
