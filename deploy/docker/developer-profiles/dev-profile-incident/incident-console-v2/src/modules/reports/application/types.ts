// SPDX-License-Identifier: Apache-2.0

// Function types the report use cases take from their caller. The caller
// supplies R2 signing, R2 deletion, VST camera deletion and the agent's embedding call, so no use
// case imports an adapter.

import type { EvidenceEmbedding, EvidenceEntry } from '@/modules/reports/domain/revision';

/** Turns a stored object key into a short-lived URL the browser can play or show. */
export type SignStorageKey = (storageKey: string) => Promise<string>;

/** Deletes a stored video object and everything derived from it (its thumbnail). */
export type RemoveStoredVideo = (storageKey: string) => Promise<unknown>;

/** Deletes the VST camera (sensor) of a video; one the VST no longer has counts as deleted. */
export type RemoveVstSensor = (video: { videoId: string; sensorId: string | null; fileName: string }) => Promise<unknown>;

/** The agent's embeddings for the evidence of one stored revision. */
export type EmbedRevisionEvidence = (revisionId: number) => Promise<EvidenceEmbedding[]>;

/** The agent's embeddings for evidence entries that are not stored yet (a revision being saved). */
export type EmbedEvidence = (evidence: EvidenceEntry[]) => Promise<EvidenceEmbedding[]>;

/** One object in the evidence area of R2. */
export interface StoredObject {
  key: string;
  /** null when the store did not say; such an object is never treated as old enough to delete. */
  lastModified: Date | null;
}

/** Lists and removes evidence images in R2. */
export interface EvidenceObjectStore {
  /** Every object whose key starts with `prefix`, across all pages. Throws rather than answer with a partial list. */
  list(prefix: string): Promise<StoredObject[]>;
  remove(key: string): Promise<void>;
}
