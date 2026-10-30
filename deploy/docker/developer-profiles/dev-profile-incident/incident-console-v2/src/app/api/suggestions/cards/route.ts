// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters, getMatchingPorts } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { listSuggestionCards } from '@/modules/matching/application/list-suggestion-cards';

export const dynamic = 'force-dynamic';

// The pending match suggestions as review cards: both incidents of each pair with title, video names and thumbnail.
// `?incidentId=` keeps those naming that incident.
export async function GET(request: Request) {
  try {
    const raw = new URL(request.url).searchParams.get('incidentId');
    const incidentId = raw === null ? undefined : Number(raw);
    if (incidentId !== undefined && !(Number.isInteger(incidentId) && incidentId > 0)) {
      return NextResponse.json({ error: 'incidentId must be a positive integer' }, { status: 400 });
    }
    const config = getServiceConfiguration();
    const sign = async (key: string) => {
      try {
        return await createR2PlaybackUrl(config, key);
      } catch {
        return undefined;
      }
    };
    const suggestions = await listSuggestionCards(
      { suggestions: getMatchingPorts(config).suggestions, reports: getDbAdapters(config).incidentReports },
      sign,
      incidentId,
    );
    return NextResponse.json({ suggestions });
  } catch (error) {
    return errorResponse(error, 'Could not list the match suggestions');
  }
}
