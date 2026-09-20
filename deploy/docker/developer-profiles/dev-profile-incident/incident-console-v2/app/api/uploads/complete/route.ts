// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, readUpstream } from '@/lib/http';

export async function POST(request: Request) {
  try {
    const { sensorId, filename } = (await request.json()) as { sensorId?: string; filename?: string };
    if (!sensorId) return NextResponse.json({ error: 'A sensor ID is required' }, { status: 400 });
    const config = getServiceConfiguration();
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured');

    const response = await fetch(
      `${config.agentUrl.replace(/\/$/, '')}/api/v1/videos/${encodeURIComponent(sensorId)}/complete`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filename }),
        cache: 'no-store',
      },
    );
    const payload = await readUpstream(response, 'Video upload completion');
    return NextResponse.json(payload);
  } catch (error) {
    return errorResponse(error, 'Could not complete the upload');
  }
}
