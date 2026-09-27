// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { allowedModels } from '@/lib/contract/load';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';

export const dynamic = 'force-dynamic';

/** The allowlisted VLMs (contracts/inference.json) the console may analyse with; no secrets. */
export async function GET() {
  try {
    const config = getServiceConfiguration();
    const models = allowedModels().map(({ id, label }) => ({ id, label }));
    const defaultModel = models.some((model) => model.id === config.vlmModel) ? config.vlmModel : models[0]?.id;
    return NextResponse.json({ models, defaultModel, modelSelection: config.analysisMode === 'gateway' });
  } catch (error) {
    return errorResponse(error, 'Could not load the available models');
  }
}
