// SPDX-License-Identifier: Apache-2.0

// Before the applier runs, a proposed re-track still needs the tracker's answer: this runs the same box/track call the box
// tool makes, from the action's seed, and puts the track into the action. Nothing is stored; a failed call leaves the action
// without a track, so the applier skips it with a reason instead of the whole request failing.

import type { AgentAction } from '@/lib/edits/apply-agent-actions';
import { TRACK_WINDOW_SECONDS } from '@/lib/evidence/box-tool';
import type { BoxToolClient } from '@/lib/evidence/box-tool-client';
import { findDraftItem } from '@/lib/evidence/evidence-proposals';
import { draftItemName } from '@/lib/reports/compare';
import type { EditDraft } from '@/modules/reports/domain/edit-draft';
import type { Box } from '@/modules/reports/domain/reviewer-item';

const isRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const number = (value: unknown, fallback: number): number => (typeof value === 'number' && Number.isFinite(value) ? value : fallback);

async function withTrack(videoId: string, draft: EditDraft, action: AgentAction, client: BoxToolClient): Promise<AgentAction> {
  const args = action.args;
  if (action.tool !== 'change_evidence' || !isRecord(args) || args.op !== 'retrack' || args.track !== undefined) return action;
  const found = typeof args.itemKey === 'string' ? findDraftItem(draft, args.itemKey) : null;
  if (!found || typeof args.seconds !== 'number' || !Array.isArray(args.box)) return action;
  try {
    const track = await client.track(videoId, {
      seconds: args.seconds,
      box: args.box as Box,
      itemType: found.kind,
      name: draftItemName(found.item),
      description: found.item.description,
      backSeconds: number(args.backSeconds, TRACK_WINDOW_SECONDS),
      forwardSeconds: number(args.forwardSeconds, TRACK_WINDOW_SECONDS),
    });
    return track ? { ...action, args: { ...args, track } } : action;
  } catch {
    return action;
  }
}

/** The actions with each re-track's track filled in; every other action is returned as it came. */
export function resolveEvidenceActions(
  videoId: string,
  draft: EditDraft,
  actions: AgentAction[],
  client: BoxToolClient,
): Promise<AgentAction[]> {
  return Promise.all(actions.map((action) => withTrack(videoId, draft, action, client)));
}
