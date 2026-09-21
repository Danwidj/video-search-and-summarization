// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, readUpstream } from '@/lib/http';

export async function POST(request: Request) {
  try {
    const { filename } = (await request.json()) as { filename?: string };
    if (!filename?.trim()) return NextResponse.json({ error: 'A filename is required' }, { status: 400 });
    const config = getServiceConfiguration();
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');

    const response = await fetch(`${config.agentUrl.replace(/\/$/, '')}/api/v1/videos`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename }),
      cache: 'no-store',
    });
    const payload = await readUpstream(response, 'Video upload initialization');
    return NextResponse.json(payload);
  } catch (error) {
    return errorResponse(error, 'Could not initialize the upload');
  }
}
