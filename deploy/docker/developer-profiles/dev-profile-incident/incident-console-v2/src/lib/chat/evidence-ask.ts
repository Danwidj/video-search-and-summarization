// SPDX-License-Identifier: Apache-2.0

// New evidence in the report chat: the editor opens the box tool at once, from the reviewer's message (at a second with a
// name; the reviewer draws the box). It asks no question first (2026-11-09). Neither is a draft change. Pure and browser-safe.

import type { ProposedAction } from '@/lib/edits/chat-edit';
import { type BoxOpening, isItemOpening } from '@/lib/evidence/box-tool';
import { findDraftItem } from '@/lib/evidence/evidence-proposals';
import { draftItemName } from '@/lib/reports/compare';
import type { EditDraft } from '@/modules/reports/domain/edit-draft';
import { formatClock } from '@/modules/reports/domain/normalize';

export const OPEN_BOX_TOOL = 'propose_open_box_tool';

/** The chat turn fields the new-evidence flow reads. */
export interface EvidenceTurn {
  role: 'user' | 'assistant';
  content: string;
  /** The box tool was opened by the editor's reply: on new evidence, or on an existing item to redraw it. */
  openedBox?: BoxOpening;
}

export interface EvidenceActions {
  /** The box tool's opening: new evidence (its second and name), or an existing draft item to redraw. */
  opening?: BoxOpening;
  /** The other proposals, which change the draft. */
  rest: ProposedAction[];
}

/**
 * Takes the box tool's opening out of the editor's actions; the rest go on to the draft. An opening on an existing item
 * carries only its key, so the item is found in the draft the chat was sent with (`draft`); the agent checked it there.
 */
export function splitEvidenceActions(actions: ProposedAction[], draft: EditDraft | null): EvidenceActions {
  const split: EvidenceActions = { rest: [] };
  for (const action of actions) {
    if (action.tool === OPEN_BOX_TOOL) {
      const { item_key: itemKey, seconds, name } = action.args;
      if (typeof itemKey === 'string') {
        const found = draft ? findDraftItem(draft, itemKey) : null;
        if (found) split.opening = { itemKey, name: draftItemName(found.item) };
      } else if (typeof seconds === 'number' && typeof name === 'string' && name.trim()) {
        split.opening = { seconds, name };
      }
    } else {
      split.rest.push(action);
    }
  }
  return split;
}

export interface EvidenceRow {
  /** Opened: the box tool on new evidence. Redraw: the box tool on an existing item. */
  kind: 'opened' | 'redraw';
  text: string;
}

/** The new-evidence step of one reply, for "What I did": the box tool's opening. */
export function evidenceRows(turn: Pick<EvidenceTurn, 'openedBox'>): EvidenceRow[] {
  const { openedBox } = turn;
  if (!openedBox) return [];
  if (isItemOpening(openedBox)) return [{ kind: 'redraw', text: `Opened the box tool on "${openedBox.name}" to redraw its box` }];
  return [{ kind: 'opened', text: `Opened the box tool at ${formatClock(openedBox.seconds)} as "${openedBox.name}"` }];
}
