// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getMatchingPorts } from '@/lib/container';
import { errorResponse } from '@/lib/http';
import { listPendingSuggestions } from '@/modules/matching/application/decide-suggestion';

// The pending match suggestions, highest score first. `?incidentId=` keeps those naming that incident.
export async function GET(request: Request) {
  try {
    const raw = new URL(request.url).searchParams.get('incidentId');
    const incidentId = raw === null ? undefined : Number(raw);
    if (incidentId !== undefined && !(Number.isInteger(incidentId) && incidentId > 0)) {
      return NextResponse.json({ error: 'incidentId must be a positive integer' }, { status: 400 });
    }
    return NextResponse.json({ suggestions: await listPendingSuggestions(getMatchingPorts().suggestions, incidentId) });
  } catch (error) {
    return errorResponse(error, 'Could not list the match suggestions');
  }
}
