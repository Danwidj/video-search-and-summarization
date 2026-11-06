// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { sendVideoCheck } from '@/modules/chat/infrastructure/agent/agent-chat';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, UpstreamError } from '@/lib/http';

export const maxDuration = 120;

/** A reviewer's confirmed fresh look at the video. The agent refuses it unless its video checks are on. */
export async function POST(request: Request) {
  try {
    const input = (await request.json()) as { videoId?: string; question?: string; storedAnswer?: string };
    if (!input.videoId || !input.question?.trim() || !input.storedAnswer?.trim())
      return NextResponse.json({ error: 'A video, a question and the stored answer are required' }, { status: 400 });
    const config = getServiceConfiguration();
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');
    const result = await sendVideoCheck(
      config.agentUrl,
      input.videoId,
      { question: input.question, storedAnswer: input.storedAnswer },
      AbortSignal.timeout(115000),
    );
    return NextResponse.json(result);
  } catch (error) {
    if (error instanceof UpstreamError)
      return NextResponse.json({ error: error.message }, { status: error.status >= 400 && error.status < 500 ? error.status : 502 });
    return errorResponse(error, 'Video check failed');
  }
}
