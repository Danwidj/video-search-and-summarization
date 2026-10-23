// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { AnalysisRequestError } from '@/lib/analysis/run-contract-analysis';
import { errorResponse } from '@/lib/http';

/** HTTP response for an analysis failure: recorded attempt outcomes keep their status and details. */
export function analysisErrorResponse(error: unknown, fallback: string): NextResponse {
  if (error instanceof AnalysisRequestError) {
    return NextResponse.json({ error: error.message, ...(error.details || {}) }, { status: error.status });
  }
  return errorResponse(error, fallback);
}
