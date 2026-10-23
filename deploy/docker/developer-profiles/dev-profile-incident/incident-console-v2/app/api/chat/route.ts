// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { sendAgentChat } from '@/lib/chat/agent-chat';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import type { ChatMessage } from '@/lib/ports/chat';

export const maxDuration = 120;
export async function POST(request: Request) {
  try {
    const input = (await request.json()) as { messages?: ChatMessage[]; sessionId?: string; incidentId?: string };
    if (!input.messages?.length) return NextResponse.json({ error: 'At least one message is required' }, { status: 400 });
    const config = getServiceConfiguration();
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');
    const result = await sendAgentChat(
      config.agentUrl,
      {
        messages: input.messages,
        ...(input.sessionId ? { sessionId: input.sessionId } : {}),
        ...(input.incidentId ? { context: { scope: 'incident' as const, incidentId: input.incidentId } } : {}),
      },
      AbortSignal.timeout(115000),
    );
    return NextResponse.json(result);
  } catch (error) { return errorResponse(error, 'Follow-up chat failed'); }
}
