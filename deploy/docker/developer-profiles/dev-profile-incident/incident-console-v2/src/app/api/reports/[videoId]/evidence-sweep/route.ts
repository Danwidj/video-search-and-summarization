// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters } from '@/lib/container';
import { getServiceConfiguration, isR2Configured } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { sweepOrphanEvidence } from '@/modules/reports/application/sweep-orphan-evidence';
import { R2EvidenceObjectStore } from '@/modules/reports/infrastructure/r2/evidence-object-store';

export const maxDuration = 60;

// Both fields are optional; the body may be empty. Nothing is removed unless dryRun is false.
const requestSchema = z
  .object({
    dryRun: z.boolean().optional(),
    minAgeHours: z
      .number()
      .positive()
      .max(24 * 365)
      .optional(),
  })
  .strict();

/**
 * Orphan sweep for one video: lists evidence/<videoId>/ in R2 and, with
 * dryRun false, removes the objects no revision or evidence_crops row of the
 * video names and that are older than minAgeHours (default 24, at least 1).
 * A dry run, the default, only reports them. See sweepOrphanEvidence.
 */
export async function POST(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const text = (await request.text()).trim();
    const parsed = requestSchema.safeParse(
      text
        ? (() => {
            try {
              return JSON.parse(text) as unknown;
            } catch {
              return null;
            }
          })()
        : {},
    );
    if (!parsed.success) {
      return NextResponse.json(
        { error: 'The body must be empty or contain dryRun (boolean) and minAgeHours (number) only' },
        { status: 400 },
      );
    }
    const config = getServiceConfiguration();
    if (!isR2Configured(config)) throw new Error('R2 is not configured');
    const report = await sweepOrphanEvidence(getDbAdapters(config).incidents, new R2EvidenceObjectStore(config), videoId, parsed.data);
    return NextResponse.json(report);
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not sweep the evidence images');
  }
}
