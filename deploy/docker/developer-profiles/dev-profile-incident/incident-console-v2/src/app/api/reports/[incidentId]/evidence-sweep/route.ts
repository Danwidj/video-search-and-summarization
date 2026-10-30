// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters } from '@/lib/container';
import { getServiceConfiguration, isR2Configured } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';
import { parseIncidentId } from '@/modules/reports/domain/incident-id';
import { sweepIncidentOrphanEvidence } from '@/modules/reports/application/sweep-orphan-evidence/incident';
import { R2EvidenceObjectStore } from '@/modules/reports/infrastructure/r2/evidence-object-store';

export const maxDuration = 60;

// video names the camera to sweep; dryRun and minAgeHours are optional. Nothing is removed unless dryRun is false.
const requestSchema = z
  .object({
    video: z.string().trim().min(1).max(512),
    dryRun: z.boolean().optional(),
    minAgeHours: z
      .number()
      .positive()
      .max(24 * 365)
      .optional(),
  })
  .strict();

/**
 * Orphan sweep for one video of the incident: lists evidence/<video key>/ in R2 and, with
 * dryRun false, removes the objects no revision or evidence_crops row of the
 * video names and that are older than minAgeHours (default 24, at least 1).
 * A dry run, the default, only reports them. Only keys under the R2 prefix are listed or removed. See sweepIncidentOrphanEvidence.
 */
export async function POST(request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const incidentId = parseIncidentId((await context.params).incidentId);
    if (incidentId === null) return NextResponse.json({ error: 'The incident id must be a positive integer' }, { status: 400 });
    const parsed = requestSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) {
      return NextResponse.json(
        { error: 'The body must contain video (a name) and optionally dryRun (boolean) and minAgeHours (number)' },
        { status: 400 },
      );
    }
    const { video, ...options } = parsed.data;
    const config = getServiceConfiguration();
    if (!isR2Configured(config)) throw new Error('R2 is not configured');
    const report = await sweepIncidentOrphanEvidence(
      getDbAdapters(config).incidentReports,
      new R2EvidenceObjectStore(config),
      incidentId,
      video,
      options,
    );
    return NextResponse.json(report);
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not sweep the evidence images');
  }
}
