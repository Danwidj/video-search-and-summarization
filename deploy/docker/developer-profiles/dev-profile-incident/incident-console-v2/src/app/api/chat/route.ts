// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { sendAgentChat, sendAgentInvestigate } from '@/modules/chat/infrastructure/agent/agent-chat';
import { chatErrorResponse } from '@/modules/chat/infrastructure/agent/chat-errors';
import { getServiceConfiguration, isChatStepsEnabled } from '@/lib/env';
import { UpstreamError } from '@/lib/http';
import { applyAgentActions } from '@/lib/edits/apply-agent-actions';
import type { EditDraft } from '@/modules/reports/domain/edit-draft';
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
    };
    if (!input.messages?.length) return NextResponse.json({ error: 'At least one message is required' }, { status: 400 });
    if (input.versionId != null && !(Number.isInteger(input.versionId) && input.versionId >= 1))
      return NextResponse.json({ error: 'versionId must be a positive integer' }, { status: 400 });
    if (input.draftReport != null && input.versionId == null)
      return NextResponse.json({ error: 'A draft report needs the versionId it was edited from' }, { status: 400 });
    const config = getServiceConfiguration();
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');

    const stepsRequested = isChatStepsEnabled(request) || input.steps === true;
    if (stepsRequested && input.incidentId) {
      const lastQuestion = [...input.messages]
        .reverse()
        .find((m) => m.role === 'user')
        ?.content?.trim();
      if (lastQuestion) {
        try {
          const investigateResult = await sendAgentInvestigate(
            config.agentUrl,
            input.incidentId,
            lastQuestion,
            AbortSignal.timeout(115000),
          );
          if (investigateResult.message.actions?.length && input.draftReport) {
            try {
              const actions = investigateResult.message.actions.map((act, index) => ({
                id: `action-${index + 1}`,
                tool: act.tool,
                args: act.args,
              }));
              const outcome = applyAgentActions(input.draftReport as unknown as EditDraft, actions);
              investigateResult.message.applied = outcome.applied;
              investigateResult.message.skipped = outcome.skipped;
            } catch {
              // draft applying failure keeps raw investigator result
            }
          }
          return NextResponse.json(investigateResult);
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
