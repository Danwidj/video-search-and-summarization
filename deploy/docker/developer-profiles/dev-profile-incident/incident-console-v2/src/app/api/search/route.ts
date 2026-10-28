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

/** A search across every incident returns a bounded list; one incident's evidence is listed whole (the agent's cap is 50). */
const TOP_K = 20;
const SCOPED_TOP_K = 50;

async function searchedVersions(
  config: ReturnType<typeof getServiceConfiguration>,
  videoIds: Set<string>,
): Promise<Record<string, SearchedVersion>> {
  if (!videoIds.size) return {};
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
    const wanted = items.filter((item: ReportLibraryItem) => videoIds.has(item.videoId));
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
    const input = (await request.json().catch(() => ({}))) as { query?: unknown; videoId?: unknown };
    const query = typeof input.query === 'string' ? input.query.trim() : '';
    const videoId = typeof input.videoId === 'string' ? input.videoId.trim() : '';
    if (videoId.length > 64) return NextResponse.json({ error: 'Invalid incident id' }, { status: 400 });
    // An empty query is the incident's evidence listing: only an incident-scoped search may be empty.
    if ((!query && !videoId) || query.length > 500) {
      return NextResponse.json({ error: 'Enter 1 to 500 characters to search for' }, { status: 400 });
    }
    const config = getServiceConfiguration();
    if (!config.agentUrl) throw new Error('INCIDENT_AGENT_BASE_URL is not configured; the agent runs evidence search');
    const result = await new AgentSearchRepository(config.agentUrl, AbortSignal.timeout(115_000)).search({
      query,
      topK: videoId ? SCOPED_TOP_K : TOP_K,
      minSimilarity: 0,
      ...(videoId ? { filters: { videoId } } : {}),
    });
    const versions = await searchedVersions(config, new Set(result.hits.map((hit) => hit.incident.videoId)));
    return NextResponse.json({ ...result, versions });
  } catch (error) {
    return errorResponse(error, 'Evidence search failed');
  }
}
