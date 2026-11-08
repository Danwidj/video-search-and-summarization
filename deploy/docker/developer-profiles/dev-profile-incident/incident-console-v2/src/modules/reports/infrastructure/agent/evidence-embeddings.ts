// SPDX-License-Identifier: Apache-2.0

// The agent's evidence-embeddings endpoint: given evidence items with their
// name and description, it embeds each one and returns one vector per item. The
// console always sends the text each crop row will store (evidenceSearchTexts),
// never a revision id: the agent would then read the bare evidence entries, which
// for a placeholder or a reviewer's new image carry no text and embed as ": ".
// The console passes the vectors to set_official_revision or
// save_human_revision_with_crops, which write them with the evidence_crops rows;
// the console never embeds anything itself.

import type { ServiceConfiguration } from '@/lib/env';
import type { EvidenceEmbedding, EvidenceSearchText } from '@/modules/reports/domain/revision';

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

/**
 * Asks the agent for the summary vector of a report: its incident type, title and description, embedded as a passage with the model
 * the AI versions use. The vector is what the Find incidents text search matches, so a human version needs one too.
 */
export async function fetchSummaryEmbedding(
  config: ServiceConfiguration,
  summary: { incidentType: string | null; title: string | null; description: string | null },
  signal?: AbortSignal,
): Promise<number[]> {
  if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured; the agent embeds the summary of a report');
  let response: Response;
  try {
    response = await fetch(`${config.agentUrl.replace(/\/$/, '')}/api/v1/incidents/revision-embedding`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ incident_type: summary.incidentType, title: summary.title, description: summary.description }),
      signal: signal ?? AbortSignal.timeout(60_000),
    });
  } catch (error) {
    throw new AgentUnreachableError(
      `Could not reach the agent to embed the summary: ${error instanceof Error ? error.message : String(error)}`,
    );
  }
  if (!response.ok)
    throw new Error(
      `The agent returned HTTP ${response.status} embedding the summary: ${(await response.text().catch(() => '')).slice(0, 300)}`,
    );
  const body = (await response.json()) as { embedding?: unknown };
  const { embedding } = body ?? {};
  if (
    !Array.isArray(embedding) ||
    embedding.length !== EMBEDDING_DIMENSIONS ||
    !embedding.every((n) => typeof n === 'number' && Number.isFinite(n))
  )
    throw new Error(`The agent returned a malformed summary embedding (expected ${EMBEDDING_DIMENSIONS} numbers)`);
  return embedding as number[];
}

/** The agent's `evidence` body for items: type, ID, and the name and description the crop row stores (the passage text). */
export function evidenceEmbeddingsBody(items: EvidenceSearchText[]): { evidence: EvidenceSearchText[] } {
  return {
    evidence: items.map(({ item_type, item_id, item_name, description }) => ({ item_type, item_id, item_name, description })),
  };
}

/**
 * Asks the agent to embed evidence texts (`evidenceSearchTexts`): each item's name and description as its crop row
 * stores them, so the vector matches the card. Used for every searchable crop, stored revision or not.
 */
export function fetchEvidenceItemEmbeddings(
  config: ServiceConfiguration,
  items: EvidenceSearchText[],
  signal?: AbortSignal,
): Promise<EvidenceEmbedding[]> {
  return postEvidenceEmbeddings(config, evidenceEmbeddingsBody(items), signal);
}
