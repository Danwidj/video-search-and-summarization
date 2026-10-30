// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getMatchingPorts } from '@/lib/container';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { rejectSuggestion } from '@/modules/matching/application/decide-suggestion';

// A rejected pair is remembered and never suggested again.
export async function POST(_request: Request, context: { params: Promise<{ suggestionId: string }> }) {
  try {
    const suggestionId = Number((await context.params).suggestionId);
    if (!(Number.isInteger(suggestionId) && suggestionId > 0))
      return NextResponse.json({ error: 'Invalid suggestion id' }, { status: 400 });
    return NextResponse.json(await rejectSuggestion(getMatchingPorts().suggestions, suggestionId));
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not reject the match suggestion');
  }
}
