// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { sendAgentChat, sendAgentInvestigate } from '@/modules/chat/infrastructure/agent/agent-chat';
import { chatErrorResponse } from '@/modules/chat/infrastructure/agent/chat-errors';
import { getServiceConfiguration, isChatEditsEnabled, isChatStepsEnabled } from '@/lib/env';
import { UpstreamError } from '@/lib/http';
import type { ChatMessage } from '@/modules/chat/domain/chat';

export const maxDuration = 120;
export async function POST(request: Request) {
  try {
    const input = (await request.json()) as {
      messages?: ChatMessage[];
      sessionId?: string;
      incidentId?: string;
      evidenceCropIds?: string[];
      versionId?: number;
      draftReport?: Record<string, unknown>;
      steps?: boolean;
      /** The draft snapshot (lib/edits/chat-edit.ts) the page sends when the chat may edit; ignored unless the edits flag is on. */
      editDraft?: Record<string, unknown>;
    };
    if (!input.messages?.length) return NextResponse.json({ error: 'At least one message is required' }, { status: 400 });
    if (input.versionId != null && !(Number.isInteger(input.versionId) && input.versionId >= 1))
      return NextResponse.json({ error: 'versionId must be a positive integer' }, { status: 400 });
    if (input.draftReport != null && input.versionId == null)
      return NextResponse.json({ error: 'A draft report needs the versionId it was edited from' }, { status: 400 });
    const config = getServiceConfiguration();
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');

    const editing = isChatEditsEnabled() && input.editDraft != null && typeof input.editDraft === 'object';
    const stepsRequested = isChatStepsEnabled(request) || input.steps === true;
    if ((stepsRequested || editing) && input.incidentId) {
      const lastQuestion = [...input.messages]
        .reverse()
        .find((m) => m.role === 'user')
        ?.content?.trim();
      if (lastQuestion) {
        try {
          const { agentUrl } = config;
          const incidentId = input.incidentId as string;
          const investigate = (draft?: Record<string, unknown>) =>
            sendAgentInvestigate(agentUrl, incidentId, lastQuestion, AbortSignal.timeout(115000), draft);
          const edited = editing ? await investigate(input.editDraft) : null;
          // An editor that ran no tool was not asked to edit: the question goes on to the usual routes, unchanged.
          if (edited?.message.steps?.length) return NextResponse.json(edited);
          if (stepsRequested) return NextResponse.json(await investigate());
        } catch (investigateError) {
          // If the agent endpoint is 404 or 501, fall through to stock agent chat
          if (!(investigateError instanceof UpstreamError && (investigateError.status === 404 || investigateError.status === 501))) {
            return chatErrorResponse(investigateError, 'Follow-up chat (investigator)');
          }
        }
      }
    }

    const result = await sendAgentChat(
      config.agentUrl,
      {
        messages: input.messages,
        ...(input.sessionId ? { sessionId: input.sessionId } : {}),
        ...(input.incidentId
          ? {
              context: {
                scope: 'incident' as const,
                incidentId: input.incidentId,
                ...(input.evidenceCropIds?.length ? { evidenceCropIds: input.evidenceCropIds } : {}),
              },
            }
          : {}),
        ...(input.versionId != null ? { versionId: input.versionId } : {}),
        ...(input.draftReport != null ? { draftReport: input.draftReport } : {}),
      },
      AbortSignal.timeout(115000),
    );
    return NextResponse.json(result);
  } catch (error) {
    // The agent's own 4xx (a version of another incident, no official version, ...) is kept for the panel to show;
    // its 5xx (model or store failure) is a bad gateway here.
    return chatErrorResponse(error, 'Follow-up chat');
  }
}
