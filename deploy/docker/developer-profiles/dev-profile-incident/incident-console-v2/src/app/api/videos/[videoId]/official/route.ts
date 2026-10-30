// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';
import { z } from 'zod';

import { getDbAdapters } from '@/lib/container';
import { parseIncidentId } from '@/lib/incident-route';
import { clearIncidentOfficialRevision, setIncidentOfficialRevision } from '@/modules/reports/application/set-official-revision/incident';
import { AgentUnreachableError, fetchEvidenceItemEmbeddings } from '@/modules/reports/infrastructure/agent/evidence-embeddings';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse, rejectionResponse } from '@/lib/http';

// Marks one revision of the incident official, or clears it. The path segment is the incident id (the folder keeps
// its old name so the client URL is unchanged). Only a reviewer action does either; analysis and saving never do.
// Marking rebuilds the incident's evidence_crops from the revision, with the agent's embeddings; clearing rebuilds
// them from the newest revision. There is no record of who or when.

const selectSchema = z.object({ revisionId: z.number().int().positive() }).strict();

const badId = () => NextResponse.json({ error: 'The incident id must be a positive integer' }, { status: 400 });

export async function PUT(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const incidentId = parseIncidentId((await context.params).videoId);
    if (incidentId === null) return badId();
    const parsed = selectSchema.safeParse(await request.json().catch(() => null));
    if (!parsed.success) return NextResponse.json({ error: 'revisionId is required' }, { status: 400 });
    const config = getServiceConfiguration();
    const result = await setIncidentOfficialRevision(
      getDbAdapters(config).incidentReports,
      incidentId,
      parsed.data.revisionId,
      (evidence) => fetchEvidenceItemEmbeddings(config, evidence),
    );
    return NextResponse.json({ official: result });
  } catch (error) {
    if (error instanceof AgentUnreachableError) {
      return NextResponse.json(
        { error: 'The agent service is not reachable, so this report could not be made official. Start the agent service and try again.' },
        { status: 503 },
      );
    }
    return rejectionResponse(error) ?? errorResponse(error, 'Could not mark the revision official');
  }
}

export async function DELETE(_request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const incidentId = parseIncidentId((await context.params).videoId);
    if (incidentId === null) return badId();
    const config = getServiceConfiguration();
    const result = await clearIncidentOfficialRevision(getDbAdapters(config).incidentReports, incidentId, (evidence) =>
      fetchEvidenceItemEmbeddings(config, evidence),
    );
    return NextResponse.json({ official: result });
  } catch (error) {
    return rejectionResponse(error) ?? errorResponse(error, 'Could not clear the official revision');
  }
}
