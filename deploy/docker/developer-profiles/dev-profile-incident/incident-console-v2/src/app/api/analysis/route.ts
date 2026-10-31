// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getUploadAnalysis } from '@/lib/container';
import { analysisErrorResponse } from '@/lib/http/analysis-responses';
import { analyseUpload } from '@/modules/analysis/application/analyse-upload';
import { requireAnalysisConfiguration, type ServiceConfiguration } from '@/lib/env';

// The slowest allowlisted model's timeout (contracts/inference.json) plus persistence.
// The upload page runs analyses as background jobs (lib/jobs/loop.ts), which this limit does not bind.
export const maxDuration = 360;

interface AnalysisRequest {
  filepath?: string;
  filename?: string;
  model?: string;
  additionalInstruction?: string;
}

export async function POST(request: Request) {
  try {
    let input: AnalysisRequest;
    try {
      input = (await request.json()) as AnalysisRequest;
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(`reading the analysis request failed: ${detail}`);
    }

    if (!input.filepath || !input.filename) {
      return NextResponse.json({ error: 'filepath and filename are required' }, { status: 400 });
    }

    let config: ServiceConfiguration;
    try {
      config = requireAnalysisConfiguration();
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      throw new Error(`validating service configuration failed: ${detail}`);
    }

    const report = await analyseUpload(
      { r2Key: input.filepath, model: input.model, additionalInstruction: input.additionalInstruction },
      getUploadAnalysis(config),
    );
    return NextResponse.json({ report });
  } catch (error) {
    return analysisErrorResponse(error, 'Video analysis failed');
  }
}
