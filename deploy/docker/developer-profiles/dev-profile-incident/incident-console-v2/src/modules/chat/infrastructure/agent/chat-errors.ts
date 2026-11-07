// SPDX-License-Identifier: Apache-2.0

// What the report chat panel is told when a chat request fails. A reviewer reads this, so it never carries raw JSON,
// HTTP codes or service names: those go to the server log. The agent's own `detail` is written for a reviewer.

import { NextResponse } from 'next/server';
import { UpstreamError } from '@/lib/http';

export const CHAT_UNAVAILABLE = 'The chat service is unavailable right now. Please try again in a moment.';
export const CHAT_TIMED_OUT = 'That took too long to answer. Please try again in a moment.';
export const CHAT_REFUSED = "That question couldn't be sent. Please check it and try again.";

function agentDetail(body: string): string | null {
  try {
    const detail = (JSON.parse(body) as { detail?: unknown }).detail;
    return typeof detail === 'string' && detail.trim() ? detail : null;
  } catch {
    return null;
  }
}

function isTimeout(error: unknown): boolean {
  return error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError');
}

/**
 * The response for a failed chat or video-check request. An agent 4xx keeps its status and its reason; any other
 * failure is a plain message. `keepAgentReason` also shows the reason of an agent 5xx: a video check's says what went
 * wrong with the look ("The video check timed out"), which the reviewer needs.
 */
export function chatErrorResponse(error: unknown, label: string, { keepAgentReason = false } = {}): NextResponse {
  console.error(`${label} failed:`, error);
  if (error instanceof UpstreamError) {
    const detail = agentDetail(error.body);
    if (error.status >= 400 && error.status < 500) return NextResponse.json({ error: detail ?? CHAT_REFUSED }, { status: error.status });
    return NextResponse.json({ error: (keepAgentReason ? detail : null) ?? CHAT_UNAVAILABLE }, { status: 502 });
  }
  if (isTimeout(error)) return NextResponse.json({ error: CHAT_TIMED_OUT }, { status: 504 });
  return NextResponse.json({ error: CHAT_UNAVAILABLE }, { status: 500 });
}
