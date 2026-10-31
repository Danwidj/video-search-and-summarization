// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getAnalysisJobs, getContractCatalog } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { analysisErrorResponse } from '@/lib/http/analysis-responses';
import { enqueueAnalysisJob, listAnalysisJobs } from '@/modules/jobs/application';

// The background analysis queue (lib/jobs/loop.ts runs it). GET lists every
// queued and running job plus the latest finished ones; POST queues an
// uploaded video: { filepath, filename, model? } -> { job }.

export async function GET() {
  try {
    return NextResponse.json({ jobs: await listAnalysisJobs(getAnalysisJobs()) });
  } catch (error) {
    return errorResponse(error, 'Could not list the analysis jobs');
  }
}

export async function POST(request: Request) {
  try {
    const input = (await request.json().catch(() => ({}))) as { filepath?: unknown; filename?: unknown; model?: unknown };
    const config = getServiceConfiguration();
    const job = await enqueueAnalysisJob(
      getAnalysisJobs(config),
      getContractCatalog(),
      { filePath: input.filepath, filename: input.filename, model: input.model },
      config.vlmModel,
    );
    return NextResponse.json({ job }, { status: 201 });
  } catch (error) {
    return rejectionResponse(error) ?? analysisErrorResponse(error, 'Could not queue the analysis');
  }
}
