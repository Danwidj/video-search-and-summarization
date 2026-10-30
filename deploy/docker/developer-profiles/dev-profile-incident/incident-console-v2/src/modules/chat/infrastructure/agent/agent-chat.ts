// SPDX-License-Identifier: Apache-2.0

// Adapter for the vss-agent's POST /api/v1/incidents/chat (chat-contract-v1):
// camelCase ChatRequest in, camelCase ChatResponse out.

import { readUpstream } from '@/lib/http';
import type { ChatCitation, ChatRequest, ChatResponse } from '@/modules/chat/domain/chat';

export function toAgentChatBody(request: ChatRequest): Record<string, unknown> {
  const { sessionId, messages, context, versionId, draftReport } = request;
  return {
    ...(sessionId ? { session_id: sessionId } : {}),
    messages: messages.map(({ role, content }) => ({ role, content })),
    ...(context
      ? {
          context: {
            ...(context.scope ? { scope: context.scope } : {}),
            ...(context.incidentId != null ? { incident_id: agentIncidentId(context.incidentId) } : {}),
            ...(context.evidenceCropIds != null ? { evidence_crop_ids: context.evidenceCropIds } : {}),
          },
        }
      : {}),
    ...(versionId != null ? { version_id: versionId } : {}),
    ...(draftReport != null ? { draft_report: draftReport } : {}),
  };
}

/** The agent takes the incident id as an integer; the console carries it as the text of a route segment. */
function agentIncidentId(incidentId: string): number {
  if (!/^[1-9]\d{0,17}$/.test(incidentId)) throw new RangeError('incidentId must be a positive integer');
  return Number(incidentId);
}

type AgentCitation = {
  incident_id: number | string;
  video_id?: string | null;
  item_id: string;
  item_type: ChatCitation['itemType'];
  timestamp_seconds: number;
  crop_image_url: string;
};
type AgentChatResponse = { session_id?: string; message?: { role?: string; content?: string; citations?: AgentCitation[] } };

export function fromAgentChatResponse(payload: unknown): ChatResponse {
  const { session_id: sessionId, message } = (payload ?? {}) as AgentChatResponse;
  if (!sessionId || message?.role !== 'assistant' || typeof message.content !== 'string' || !Array.isArray(message.citations)) {
    throw new Error('Agent returned an invalid chat response');
  }
  return {
    sessionId,
    message: {
      role: 'assistant',
      content: message.content,
      citations: message.citations.map((c) => ({
        incidentId: String(c.incident_id),
        videoName: typeof c.video_id === 'string' && c.video_id ? c.video_id : null,
        itemId: c.item_id,
        itemType: c.item_type,
        timestampSeconds: c.timestamp_seconds,
        cropImageUrl: c.crop_image_url,
      })),
    },
  };
}

export async function sendAgentChat(agentUrl: string, request: ChatRequest, signal?: AbortSignal): Promise<ChatResponse> {
  const response = await fetch(`${agentUrl.replace(/\/$/, '')}/api/v1/incidents/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(toAgentChatBody(request)),
    signal,
  });
  return fromAgentChatResponse(await readUpstream(response, 'Agent /api/v1/incidents/chat'));
}
