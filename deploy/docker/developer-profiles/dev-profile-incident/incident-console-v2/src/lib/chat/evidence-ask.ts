// SPDX-License-Identifier: Apache-2.0

// New evidence in the report chat: the editor asks the reviewer what it needs (the question is the chat's reply), then
// opens the box tool at a second with a name (the reviewer draws the box). Neither is a draft change. Pure and browser-safe.

import type { ProposedAction } from '@/lib/edits/chat-edit';
import { type BoxOpening, isItemOpening } from '@/lib/evidence/box-tool';
import { findDraftItem } from '@/lib/evidence/evidence-proposals';
import { draftItemName } from '@/lib/reports/compare';
import type { EvidenceExchange } from '@/modules/chat/domain/chat';
import type { EditDraft } from '@/modules/reports/domain/edit-draft';
import { formatClock } from '@/modules/reports/domain/normalize';

export const ASK_REVIEWER_TOOL = 'propose_ask_reviewer';
export const OPEN_BOX_TOOL = 'propose_open_box_tool';

/** The chat turn fields the new-evidence flow reads. */
export interface EvidenceTurn {
  role: 'user' | 'assistant';
  content: string;
  /** The questions the editor asked the reviewer about new evidence in this reply, in order. */
  questions?: string[];
  /** The box tool was opened by the editor's reply: on new evidence, or on an existing item to redraw it. */
  openedBox?: BoxOpening;
}

/**
 * The new-evidence exchange still open in the thread, or null. It starts at the reviewer's message that led to the first
 * question and ends once the box tool has opened. The last turn is the question being sent now, so it is not in the transcript.
 * The transcript keeps the reviewer's messages and the questions, not the editor's other replies.
 */
export function pendingEvidenceExchange(turns: EvidenceTurn[]): EvidenceExchange | null {
  const from = turns.findLastIndex((turn) => turn.openedBox) + 1;
  const first = turns.findIndex((turn, index) => index >= from && questionCount(turn) > 0);
  if (first < 0) return null;
  const span = turns.slice(Math.max(from, first - 1), -1);
  return {
    questionsAsked: span.reduce((total, turn) => total + questionCount(turn), 0),
    transcript: span
      .filter((turn) => turn.role === 'user' || questionCount(turn) > 0)
      .map((turn) => ({ role: turn.role === 'user' ? 'reviewer' : 'assistant', text: turn.content })),
  };
}

/** A reply can ask more than one question (at most two in all), so the count is per question, not per reply. */
const questionCount = (turn: EvidenceTurn): number => turn.questions?.length ?? 0;

export interface EvidenceActions {
  /** The questions for the reviewer, in the order asked: the chat's reply. */
  questions: string[];
  /** The box tool's opening: new evidence (its second and name), or an existing draft item to redraw. */
  opening?: BoxOpening;
  /** The other proposals, which change the draft. */
  rest: ProposedAction[];
}

/**
 * Takes the new-evidence proposals out of the editor's actions; the rest go on to the draft. An opening on an existing item
 * carries only its key, so the item is found in the draft the chat was sent with (`draft`); the agent checked it there.
 */
export function splitEvidenceActions(actions: ProposedAction[], draft: EditDraft | null): EvidenceActions {
  const split: EvidenceActions = { questions: [], rest: [] };
  for (const action of actions) {
    if (action.tool === ASK_REVIEWER_TOOL) {
      if (typeof action.args.question === 'string' && action.args.question.trim()) split.questions.push(action.args.question);
    } else if (action.tool === OPEN_BOX_TOOL) {
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
  /** Asked: a question to the reviewer. Opened: the box tool on new evidence. Redraw: the box tool on an existing item. */
  kind: 'asked' | 'opened' | 'redraw';
  text: string;
}

/** The new-evidence steps of one reply, for "What I did": the question asked, and the box tool's opening. */
export function evidenceRows(turn: Pick<EvidenceTurn, 'questions' | 'openedBox'>): EvidenceRow[] {
  const rows: EvidenceRow[] = (turn.questions ?? []).map((text) => ({ kind: 'asked', text }));
  const { openedBox } = turn;
  if (openedBox && isItemOpening(openedBox))
    rows.push({ kind: 'redraw', text: `Opened the box tool on "${openedBox.name}" to redraw its box` });
  else if (openedBox)
    rows.push({ kind: 'opened', text: `Opened the box tool at ${formatClock(openedBox.seconds)} as "${openedBox.name}"` });
  return rows;
}
