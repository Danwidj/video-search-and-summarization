// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { AgentSearchRepository } from '@/lib/adapters/agent/search';
import { getDbAdapters } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { isValidR2Key, thumbnailKeyForVideo } from '@/lib/r2/key';
import type { SearchedVersion } from '@/lib/library/search';
import type { ReportLibraryItem } from '@/modules/reports/domain/storage';

export const maxDuration = 120;
export const dynamic = 'force-dynamic';

/** A search across every incident returns a bounded list; one incident's or camera's evidence is listed whole (the agent's cap is 50). */
const TOP_K = 20;
const SCOPED_TOP_K = 50;
/** incidents.id is an identity column: a positive integer, written as text in routes. */
const INCIDENT_ID = /^[1-9]\d{0,17}$/;

async function searchedVersions(
  config: ReturnType<typeof getServiceConfiguration>,
  incidentIds: Set<string>,
): Promise<Record<string, SearchedVersion>> {
  if (!incidentIds.size) return {};
  try {
    const { items } = await getDbAdapters(config).incidents.listReports({
      page: 1,
      pageSize: 1000,
      search: null,
      type: null,
      severity: null,
      kind: null,
      generatedAfter: null,
      generatedBefore: null,
      timeFrom: null,
      timeTo: null,
      entities: null,
      instruments: null,
      assets: null,
      dayOfWeek: null,
      sort: 'newest',
      scope: 'all',
      entityTypes: null,
      evidenceMatch: 'contains',
      timezone: 'UTC',
    });
    const wanted = items.filter((item: ReportLibraryItem) => incidentIds.has(item.videoId));
    const sign = async (key: string) => {
      try {
        return await createR2PlaybackUrl(config, key);
      } catch {
        return undefined;
      }
    };
    const entries = await Promise.all(
      wanted.map(async (item) => {
        const thumbnailUrl = isValidR2Key(item.r2Key) ? await sign(thumbnailKeyForVideo(item.r2Key)) : undefined;
        return [
          item.videoId,
          {
            revisionId: item.revisionId,
            revisionNo: item.revisionNo,
            isOfficial: item.isOfficial === true,
            ...(item.title ? { title: item.title } : {}),
            ...(thumbnailUrl ? { thumbnailUrl } : {}),
          },
        ] as const;
      }),
    );
    return Object.fromEntries(entries);
  } catch {
    return {};
  }
}

export async function POST(request: Request) {
  try {
    const input = (await request.json().catch(() => ({}))) as { query?: unknown; incidentId?: unknown; videoName?: unknown };
    const query = typeof input.query === 'string' ? input.query.trim() : '';
    const incidentId = typeof input.incidentId === 'string' ? input.incidentId.trim() : '';
    const videoName = typeof input.videoName === 'string' ? input.videoName.trim() : '';
    if (incidentId && !INCIDENT_ID.test(incidentId)) return NextResponse.json({ error: 'Invalid incident id' }, { status: 400 });
    if (videoName.length > 255) return NextResponse.json({ error: 'Invalid video name' }, { status: 400 });
    // An empty query is the evidence listing of an incident or a camera: only a scoped search may be empty.
    const scoped = Boolean(incidentId || videoName);
    if ((!query && !scoped) || query.length > 500) {
      return NextResponse.json({ error: 'Enter 1 to 500 characters to search for' }, { status: 400 });
    }
    const config = getServiceConfiguration();
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured; the agent runs evidence search');
    const result = await new AgentSearchRepository(config.agentUrl, AbortSignal.timeout(115_000)).search({
      query,
      topK: scoped ? SCOPED_TOP_K : TOP_K,
      minSimilarity: 0,
      ...(scoped ? { filters: { ...(incidentId ? { incidentId } : {}), ...(videoName ? { videoName } : {}) } } : {}),
    });
    const versions = await searchedVersions(config, new Set(result.hits.map((hit) => hit.incident.incidentId)));
    return NextResponse.json({ ...result, versions });
  } catch (error) {
    return errorResponse(error, 'Evidence search failed');
  }
}
