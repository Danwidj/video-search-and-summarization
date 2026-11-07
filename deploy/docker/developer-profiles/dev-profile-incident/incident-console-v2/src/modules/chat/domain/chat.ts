// SPDX-License-Identifier: Apache-2.0

// IncidentChat (MVP2): multi-turn Q&A with cited evidence. These types are the
// vss-agent's POST /api/v1/incidents/chat contract (chat-contract-v1,
// services/agent/src/vss_agents/api/incident_chat.py ChatRequest / ChatResponse)
// in camelCase; modules/chat/infrastructure/agent/agent-chat.ts maps the snake_case.

import type { EvidenceItemType } from '@/modules/search/domain/search';

export type ChatRole = 'user' | 'assistant' | 'system';

export interface ChatMessage {
  role: ChatRole;
  /** At least 1 character. */
  content: string;
}

export interface ChatContext {
  /** Default global. */
  scope?: 'global' | 'incident';
  /** The incident to focus on when scope is incident. */
  incidentId?: string | null;
  evidenceCropIds?: string[] | null;
}

export interface ChatRequest {
  /** 1 to 128 characters; the agent generates one when absent. */
  sessionId?: string;
  /** At least one; the last user message is the query. */
  messages: ChatMessage[];
  context?: ChatContext;
  /** The saved report version (report_revisions.id) the question is about; citations come from it. */
  versionId?: number;
  /** An unsaved incident report edited from versionId; answers are grounded in it. Requires versionId. */
  draftReport?: Record<string, unknown>;
}

export interface ChatCitation {
  incidentId: string;
  itemId: string;
  itemType: EvidenceItemType;
  /** 0 or more, for jump-to-clip. */
  timestampSeconds: number;
  /** Signed by the agent; used as given. */
  cropImageUrl: string;
}

/** chat-contract-v2 and v3 (agent INCIDENT_CHAT_MODE=grounded or routed): which report the answer is grounded in. */
export interface ChatGrounding {
  mode: 'grounded' | 'routed';
  scope: 'incident' | 'library';
  model: string;
  /** The report version answered from; null for a library question. */
  versionId: number | null;
  official: boolean | null;
  draft: boolean;
  /** Item ids the model cited that the report does not hold (never shown as citations). */
  droppedCitations: string[];
  /** Ids the model wrote in the answer text although not asked; the agent replaced each with a description. */
  idsResolved: string[];
  /** Library answers: how each incident shown is named (type and title), keyed by incident id, for id-free labels. */
  incidentTitles: Record<string, string>;
  /** Library answers: how each cited item is named ("the glass bottle"), keyed by `incidentId/itemId`. */
  itemNames: Record<string, string>;
  /** Library answers: the report version each incident shown was read from, for links to that version. */
  versions: Record<string, number>;
  /** Library answers: the best matching incidents (shown to the model, or named in a count). */
  candidates: string[];
  /** Library answers: `code` composed a count or breakdown from exact counts; `model` answered from the reports. */
  answeredBy: 'model' | 'code' | null;
  /** Library answers: whether the filters captured the whole question, so the count is exact. */
  countExact: boolean | null;
  /** Routed answers: which route answered; null otherwise. */
  route: 'deterministic' | 'report_llm' | 'insufficient' | null;
  /** Routed answers: times written in the answer that the report does not hold. They must not be linked. */
  unknownTimes: string[];
}

/** chat-contract-v3: a check of the original video may be offered. It never runs without the reviewer's click. */
export interface VideoOffer {
  reason: string;
  /** The check needs footage after this second; absent when any footage will do. */
  fromSeconds?: number;
}

/** What POST /api/v1/incidents/{id}/video-check returns: a fresh look, apart from the stored report. */
export interface VideoCheckResult {
  content: string;
  source: 'video';
}

/** A step executed by a tool-calling agent (from PR 517 /api/v1/incidents/{video_id}/investigate). */
export interface ChatStep {
  tool: string;
  args?: Record<string, unknown>;
  ok: boolean;
  ms: number;
  error?: string | null;
}

/** Action applied to the draft. */
export interface AppliedAction {
  id?: string;
  tool: string;
  note?: string;
}

/** Action skipped when applying to draft. */
export interface SkippedAction {
  id?: string;
  tool: string;
  reason: string;
}

/** The new-evidence exchange still open in the report chat (lib/chat/evidence-ask.ts), sent with the question it leads to. */
export interface EvidenceExchange {
  questionsAsked: number;
  transcript: Array<{ role: 'reviewer' | 'assistant'; text: string }>;
}

export interface ChatResponse {
  sessionId: string;
  message: {
    role: 'assistant';
    content: string;
    citations: ChatCitation[];
    /** chat-contract-v2: the report cannot answer (or contradicts the question); citations are then empty. */
    insufficientEvidence?: boolean;
    /** chat-contract-v3: composed by code, read from the report by the chat model, or run by the investigator agent. */
    source?: 'report' | 'report_llm' | 'video' | 'investigator';
    videoOffer?: VideoOffer;
    steps?: ChatStep[];
    actions?: Array<{ tool: string; args: Record<string, unknown> }>;
    applied?: AppliedAction[];
    skipped?: SkippedAction[];
    wallMs?: number;
    status?: string;
  };
  grounding?: ChatGrounding;
}
