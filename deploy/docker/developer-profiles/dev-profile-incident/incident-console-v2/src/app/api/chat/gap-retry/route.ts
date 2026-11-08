// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { readGapRetry, startGapRetry } from '@/modules/chat/infrastructure/agent/agent-chat';
import { chatErrorResponse } from '@/modules/chat/infrastructure/agent/chat-errors';
import { getServiceConfiguration } from '@/lib/env';

export const maxDuration = 30;

/** Starts a gap retry of a report's items with no box (`itemKey` alone: one item). The agent returns at once with a job. */
export async function POST(request: Request) {
  try {
    const input = (await request.json()) as { videoId?: string; itemKey?: string | null };
    if (!input.videoId) return NextResponse.json({ error: 'A video is required' }, { status: 400 });
    const config = getServiceConfiguration();
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');
    const job = await startGapRetry(config.agentUrl, input.videoId, input.itemKey ?? null, AbortSignal.timeout(25000));
    return NextResponse.json(job, { status: 202 });
  } catch (error) {
    return chatErrorResponse(error, 'Gap retry', { keepAgentReason: true });
  }
}

/** One gap retry job as it stands: its items, and whether it is done. The chat polls it until it is. */
export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const videoId = searchParams.get('videoId');
    const jobId = searchParams.get('jobId');
    if (!videoId || !jobId) return NextResponse.json({ error: 'A video and a job are required' }, { status: 400 });
    const config = getServiceConfiguration();
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');
    const job = await readGapRetry(config.agentUrl, videoId, jobId, AbortSignal.timeout(25000));
    return NextResponse.json(job);
  } catch (error) {
    return chatErrorResponse(error, 'Gap retry', { keepAgentReason: true });
  }
}
