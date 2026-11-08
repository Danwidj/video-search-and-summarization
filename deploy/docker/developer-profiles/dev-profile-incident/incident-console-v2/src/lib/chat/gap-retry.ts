// SPDX-License-Identifier: Apache-2.0

// Gap retry in the report chat: the editor asks for a retry of the items with no box, the agent looks for each one in the clip
// with the video model, and each box it finds comes back as an evidence proposal (set image) for the reviewer to confirm or
// adjust. The chat says what it started and, once the job is done, what was found and why nothing was. Pure and browser-safe.

import type { ProposedAction } from '@/lib/edits/chat-edit';
import { formatClock } from '@/modules/reports/domain/normalize';

export const GAP_RETRY_TOOL = 'propose_retry_gaps';
export const CHANGE_EVIDENCE_TOOL = 'change_evidence';

/** One gap retry the editor asked for: one item by its draft key, or (null) every item with no box. */
export interface GapRetryRequest {
  itemKey: string | null;
}

/** An item of a gap retry job, as the console reads it. `found` carries the box to propose (seconds and a 0-1000 box). */
export interface GapRetryItem {
  itemKey: string;
  name: string;
  status: 'pending' | 'found' | 'not_found' | 'not_retried';
  reason: string | null;
  seconds: number | null;
  box: number[] | null;
}

export interface GapRetryJob {
  jobId: string;
  videoId: string;
  revisionId: number | null;
  status: 'running' | 'done';
  items: GapRetryItem[];
}

export interface GapRetrySplit {
  retries: GapRetryRequest[];
  rest: ProposedAction[];
}

/** Takes the gap-retry requests out of the editor's actions; the rest go on to the draft. */
export function splitGapRetryActions(actions: ProposedAction[]): GapRetrySplit {
  const split: GapRetrySplit = { retries: [], rest: [] };
  for (const action of actions) {
    if (action.tool !== GAP_RETRY_TOOL) {
      split.rest.push(action);
      continue;
    }
    const key = action.args.item_key;
    split.retries.push({ itemKey: typeof key === 'string' && key.trim() ? key : null });
  }
  return split;
}

/**
 * A draft item as the id mapping reads it. The draft's `key` is its own (what the editor and the applier use); the report and
 * the agent know an item by `sourceId` (its id in the report) or, for an entity, `canonicalId` (the same id).
 */
export interface DraftItemIds {
  key: string;
  sourceId?: string | null;
  canonicalId?: string;
}

/** The id the report and the agent know a draft item by, or null for an item the reviewer added (not in the report). */
export function reportIdOf(items: DraftItemIds[], key: string): string | null {
  const item = items.find((candidate) => candidate.key === key);
  return item?.sourceId || item?.canonicalId || null;
}

/** The draft key of the item the report knows as `reportId`, or null when the draft has no such item. */
export function draftKeyOf(items: DraftItemIds[], reportId: string): string | null {
  return items.find((candidate) => candidate.sourceId === reportId || candidate.canonicalId === reportId)?.key ?? null;
}

/** The found boxes as set-image proposals on their items: the reviewer confirms or adjusts each one before Save. */
export function gapRetryProposals(job: GapRetryJob, items: DraftItemIds[]): ProposedAction[] {
  return job.items
    .filter((item) => item.status === 'found' && item.seconds !== null && item.box !== null)
    .map((item) => ({
      tool: CHANGE_EVIDENCE_TOOL,
      args: {
        item_key: draftKeyOf(items, item.itemKey) ?? item.itemKey,
        op: 'set_image',
        seconds: item.seconds,
        box: item.box,
        reason: 'Found by a gap retry in the clip; confirm or adjust the box.',
      },
    }));
}

/** The chat's line when a retry starts: which item, and how long it takes. */
export function gapRetryStartedText(request: GapRetryRequest, labelOf: (key: string) => string): string {
  const target = request.itemKey === null ? 'the items with no box' : labelOf(request.itemKey);
  return `I'll look for ${target} in the clip. This takes about a minute an item. Any box I find comes back here as a proposal for you to confirm or adjust.`;
}

/** The chat's reply once the job is done: one line per item, in labels and names, with the reason for each miss. */
export function gapRetryResultText(job: GapRetryJob, labelOf: (key: string) => string): string {
  const looked = job.items.filter((item) => item.status !== 'pending');
  if (!looked.length) return 'There is no item with no box to look for.';
  const found = job.items.filter((item) => item.status === 'found').length;
  const lines = [`I found a box for ${found} of ${job.items.length} ${job.items.length === 1 ? 'item' : 'items'}.`];
  for (const item of job.items) {
    const label = labelOf(item.itemKey) || item.name || item.itemKey;
    if (item.status === 'found' && item.seconds !== null)
      lines.push(`${label}: box found at ${formatClock(item.seconds)}. Confirm or adjust it on the item.`);
    else if (item.status === 'not_found') lines.push(`${label}: no box found (${item.reason ?? 'nothing matched'}).`);
    else if (item.status === 'not_retried') lines.push(`${label}: not retried (${item.reason ?? 'the retry did not run'}).`);
  }
  if (job.items.some((item) => item.status === 'not_found'))
    lines.push('To draw a box yourself, say "draw the box for" the item and I will open the box tool on it.');
  return lines.join('\n');
}
