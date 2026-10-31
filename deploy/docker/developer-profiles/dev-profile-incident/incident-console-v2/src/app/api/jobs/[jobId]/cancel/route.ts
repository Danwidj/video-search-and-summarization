// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getAnalysisJobs } from '@/lib/container';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { cancelAnalysisJob } from '@/modules/jobs/application';

// A queued job is cancelled before it runs: -> { job }; 422 for any other job.
export async function POST(_request: Request, context: { params: Promise<{ jobId: string }> }) {
  try {
    const id = Number((await context.params).jobId);
    if (!Number.isSafeInteger(id) || id < 1) return NextResponse.json({ error: 'Unknown job' }, { status: 404 });
    return NextResponse.json({ job: await cancelAnalysisJob(getAnalysisJobs(), id) });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not cancel the analysis job');
  }
}
