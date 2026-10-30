// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters, getMatchingPorts } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { acceptSuggestion } from '@/modules/matching/application/decide-suggestion';

// Accepting a suggestion merges the pair: the target incident keeps its id and takes the other's videos.
// The body is optional; `incidentId` picks the incident to keep (default: the older one).
const bodySchema = z.object({ incidentId: z.number().int().positive().optional() }).strict();

function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

export async function POST(request: Request, context: { params: Promise<{ suggestionId: string }> }) {
  try {
    const suggestionId = Number((await context.params).suggestionId);
    if (!(Number.isInteger(suggestionId) && suggestionId > 0))
      return NextResponse.json({ error: 'Invalid suggestion id' }, { status: 400 });
    const text = await request.text();
    const parsed = bodySchema.safeParse(text ? parseJson(text) : {});
    if (!parsed.success) return NextResponse.json({ error: 'incidentId must be a positive integer' }, { status: 400 });
    const config = getServiceConfiguration();
    const result = await acceptSuggestion(
      { suggestions: getMatchingPorts(config).suggestions, reports: getDbAdapters(config).incidentReports },
      suggestionId,
      parsed.data.incidentId,
    );
    return NextResponse.json(result);
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not accept the match suggestion');
  }
}
