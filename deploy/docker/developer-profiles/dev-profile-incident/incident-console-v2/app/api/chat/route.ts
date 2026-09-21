// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';

export const maxDuration = 120;
export async function POST(request: Request) {
  try {
    const input = (await request.json()) as { messages?: Array<{ role: string; content: string }>; reportContext?: string };
    if (!input.messages?.length) return NextResponse.json({ error: 'At least one message is required' }, { status: 400 });
    const config = getServiceConfiguration();
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');
    const response = await fetch(`${config.agentUrl.replace(/\/$/, '')}/chat`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ model: config.vlmModel, stream: false, temperature: 0, messages: [{ role: 'system', content: `Answer only from this incident report context. Clearly state when the report does not contain an answer.\n${input.reportContext || ''}` }, ...input.messages] }), signal: AbortSignal.timeout(115000) });
    const text = await response.text();
    if (!response.ok) throw new Error(`Agent /chat returned HTTP ${response.status}: ${text.slice(0, 500)}`);
    const payload = JSON.parse(text) as { choices?: Array<{ message?: { content?: string } }> };
    const content = payload.choices?.[0]?.message?.content;
    if (!content) throw new Error('Agent returned no chat response');
    return NextResponse.json({ content });
  } catch (error) { return errorResponse(error, 'Follow-up chat failed'); }
}
