// SPDX-License-Identifier: Apache-2.0

// New evidence in the report chat: the editor asks the reviewer what it needs (the question is the chat's reply), then
// opens the box tool at a second with a name (the reviewer draws the box). Neither is a draft change. Pure and browser-safe.

import type { ProposedAction } from '@/lib/edits/chat-edit';
import type { EvidenceOpening } from '@/lib/evidence/box-tool';
import type { EvidenceExchange } from '@/modules/chat/domain/chat';
import { formatClock } from '@/modules/reports/domain/normalize';

export const ASK_REVIEWER_TOOL = 'propose_ask_reviewer';
export const OPEN_BOX_TOOL = 'propose_open_box_tool';

/** The chat turn fields the new-evidence flow reads. */
export interface EvidenceTurn {
  role: 'user' | 'assistant';
  content: string;
  /** The editor's reply was a question to the reviewer about new evidence. */
  askedReviewer?: boolean;
  /** The box tool was opened by the editor's reply. */
  openedBox?: EvidenceOpening;
}

/**
 * The new-evidence exchange still open in the thread, or null. It starts at the reviewer's message that led to the first
 * question and ends once the box tool has opened. The last turn is the question being sent now, so it is not in the transcript.
 * The transcript keeps the reviewer's messages and the questions, not the editor's other replies.
 */
export function pendingEvidenceExchange(turns: EvidenceTurn[]): EvidenceExchange | null {
  const from = turns.findLastIndex((turn) => turn.openedBox) + 1;
  const first = turns.findIndex((turn, index) => index >= from && turn.askedReviewer === true);
  if (first < 0) return null;
  const span = turns.slice(Math.max(from, first - 1), -1);
  return {
    questionsAsked: span.filter((turn) => turn.askedReviewer).length,
    transcript: span
      .filter((turn) => turn.role === 'user' || turn.askedReviewer)
      .map((turn) => ({ role: turn.role === 'user' ? 'reviewer' : 'assistant', text: turn.content })),
  };
}

export interface EvidenceActions {
  /** The question for the reviewer: the chat's reply. */
  question?: string;
  /** The box tool's opening: the second and the name. */
  opening?: EvidenceOpening;
  /** The other proposals, which change the draft. */
  rest: ProposedAction[];
}

/** Takes the new-evidence proposals out of the editor's actions; the rest go on to the draft. */
export function splitEvidenceActions(actions: ProposedAction[]): EvidenceActions {
  const split: EvidenceActions = { rest: [] };
  for (const action of actions) {
    if (action.tool === ASK_REVIEWER_TOOL) {
      if (typeof action.args.question === 'string' && action.args.question.trim()) split.question = action.args.question;
    } else if (action.tool === OPEN_BOX_TOOL) {
      const { seconds, name } = action.args;
      if (typeof seconds === 'number' && typeof name === 'string' && name.trim()) split.opening = { seconds, name };
    } else {
      split.rest.push(action);
    }
  }
  return split;
}

export interface EvidenceRow {
  kind: 'asked' | 'opened';
  text: string;
}

/** The new-evidence steps of one reply, for "What I did": the question asked, and the box tool's opening. */
export function evidenceRows(turn: Pick<EvidenceTurn, 'content' | 'askedReviewer' | 'openedBox'>): EvidenceRow[] {
  const rows: EvidenceRow[] = [];
  if (turn.askedReviewer) rows.push({ kind: 'asked', text: turn.content });
  if (turn.openedBox)
    rows.push({ kind: 'opened', text: `Opened the box tool at ${formatClock(turn.openedBox.seconds)} as "${turn.openedBox.name}"` });
  return rows;
}
