// SPDX-License-Identifier: Apache-2.0

// The agent's evidence-embeddings endpoint: given a stored revision, or the
// evidence entries of a revision not stored yet, it embeds each evidence crop
// and returns one vector per item. The console passes the vectors to
// set_official_revision or save_human_revision_with_crops, which write them with
// the evidence_crops rows; the console never embeds anything itself.

import type { ServiceConfiguration } from '@/lib/env';
import type { EvidenceEmbedding, EvidenceEntry } from '@/modules/reports/domain/revision';

export const EMBEDDING_DIMENSIONS = 1024;

const ITEM_TYPES = ['entity', 'instrument', 'asset'];

/** The endpoint's JSON -> EvidenceEmbedding[]: a bare list (or {items}); a malformed entry is an error, never skipped. */
export function embeddingsFromResponse(body: unknown): EvidenceEmbedding[] {
  const list = Array.isArray(body)
    ? body
    : body && typeof body === 'object' && Array.isArray((body as { items?: unknown }).items)
      ? (body as { items: unknown[] }).items
      : null;
  if (!list) throw new Error('The agent returned no embedding list');
  return list.map((raw) => {
    const item = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
    const { item_type: itemType, item_id: itemId, embedding } = item;
    if (typeof itemType !== 'string' || !ITEM_TYPES.includes(itemType) || typeof itemId !== 'string' || !itemId)
      throw new Error('The agent returned an embedding without an item type and ID');
    if (
      !Array.isArray(embedding) ||
      embedding.length !== EMBEDDING_DIMENSIONS ||
      !embedding.every((n) => typeof n === 'number' && Number.isFinite(n))
    ) {
      throw new Error(`The agent returned a malformed embedding for ${itemType} ${itemId} (expected ${EMBEDDING_DIMENSIONS} numbers)`);
    }
    return { itemType: itemType as EvidenceEmbedding['itemType'], itemId, embedding: embedding as number[] };
  });
}

/** The agent did not answer at all (connection refused, DNS, timeout); the caller can say so in plain words. */
export class AgentUnreachableError extends Error {}

/** Posts a body to the agent's embedding endpoint and reads the vectors back. */
async function postEvidenceEmbeddings(
  config: ServiceConfiguration,
  body: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<EvidenceEmbedding[]> {
  if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured; the agent embeds the evidence of a report');
  const endpoint = `${config.agentUrl.replace(/\/$/, '')}/api/v1/incidents/evidence-embeddings`;
  let response: Response;
  try {
    response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: signal ?? AbortSignal.timeout(120_000),
    });
  } catch (error) {
    throw new AgentUnreachableError(
      `Could not reach the agent to embed the evidence: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  if (!response.ok)
    throw new Error(
      `The agent returned HTTP ${response.status} embedding the evidence: ${(await response.text().catch(() => '')).slice(0, 300)}`,
    );
  return embeddingsFromResponse(await response.json());
}

/** Asks the agent to embed the evidence of one stored revision. */
export function fetchEvidenceEmbeddings(
  config: ServiceConfiguration,
  revisionId: number,
  signal?: AbortSignal,
): Promise<EvidenceEmbedding[]> {
  return postEvidenceEmbeddings(config, { revision_id: revisionId }, signal);
}

/**
 * Asks the agent to embed evidence entries that are not stored yet (a revision being saved), so the crops
 * can be written in the same write as the revision. Each entry's item type, ID, name and description make its passage.
 */
export function fetchEvidenceItemEmbeddings(
  config: ServiceConfiguration,
  evidence: EvidenceEntry[],
  signal?: AbortSignal,
): Promise<EvidenceEmbedding[]> {
  const items = evidence.map((entry) => ({
    item_type: entry.item_type,
    item_id: entry.item_id,
    item_name: typeof entry.item_name === 'string' ? entry.item_name : null,
    description: typeof entry.description === 'string' ? entry.description : null,
  }));
  return postEvidenceEmbeddings(config, { evidence: items }, signal);
}
