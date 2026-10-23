// SPDX-License-Identifier: Apache-2.0

// Edge-only: maps analysis outcomes to HTTP responses for the analysis routes.
// The analysis module returns and throws plain values; NextResponse lives here.

import { NextResponse } from 'next/server';

import { errorResponse } from '@/lib/http';
import { AnalysisRequestError } from '@/modules/analysis/application/run-contract-analysis';

/** HTTP response for an analysis failure: recorded attempt outcomes keep their status and details. */
export function analysisErrorResponse(error: unknown, fallback: string): NextResponse {
  if (error instanceof AnalysisRequestError) {
    return NextResponse.json({ error: error.message, ...(error.details || {}) }, { status: error.status });
  }
  return errorResponse(error, fallback);
}
