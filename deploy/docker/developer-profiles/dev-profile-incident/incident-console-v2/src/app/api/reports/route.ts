// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { AgentRevisionSearchRepository } from '@/lib/adapters/agent/revision-search';
import { getDbAdapters } from '@/lib/container';
import { getServiceConfiguration, type ServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import type { IncidentRepository, ReportList, ReportListQuery, ReportSort } from '@/modules/reports/domain/IncidentRepository';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { isValidR2Key, thumbnailKeyForVideo } from '@/lib/r2/key';
import { isValidTimeZone } from '@/lib/time';

export const dynamic = 'force-dynamic';

const PAGE_SIZE = 6;
/** The most incidents one list reads, so a text search can filter them in memory (the RPC's own cap). */
const MAX_LIST_SIZE = 1000;
/** Revision hits asked for per text search; the agent ranks best first. */
const REVISION_TOP_K = 50;
const REVISION_SEARCH_TIMEOUT_MS = 30_000;
const SORTS = new Set(['newest', 'oldest', 'severity-high', 'severity-low', 'confidence-high', 'confidence-low']);
const SEVERITIES = new Set(['all', 'low', 'medium', 'high', '1', '2', '3', '4', '5']);

const SCOPES = new Set(['all', 'official', 'not_official']);
const MATCHES = new Set(['contains', 'exact']);
const ENTITY_TYPES = new Set(['human', 'animal', 'unknown']);
const MAX_EVIDENCE_FILTERS = 10;
const MAX_EVIDENCE_FILTER_LENGTH = 100;

const isSort = (value: string): value is ReportSort => SORTS.has(value);
const isScope = (value: string): value is ReportListQuery['scope'] => SCOPES.has(value);
const isMatch = (value: string): value is ReportListQuery['evidenceMatch'] => MATCHES.has(value);

function optional(params: URLSearchParams, key: string): string | null {
  const value = params.get(key)?.trim();
  return value && value !== 'all' ? value : null;
}

function evidenceFilters(params: URLSearchParams, key: string): string[] | null {
  const values = [
    ...new Set(
      params
        .getAll(key)
        .map((value) => value.trim())
        .filter(Boolean),
    ),
  ];
  if (values.length > MAX_EVIDENCE_FILTERS || values.some((value) => value.length > MAX_EVIDENCE_FILTER_LENGTH)) {
    throw new RangeError(`Invalid ${key} filter`);
  }
  return values.length ? values : null;
}

/**
 * The videos whose saved revisions the agent ranks for the text. Null when the
 * agent is not configured, fails or finds nothing, so the caller keeps the
 * ILIKE text filter (the store's own search).
 */
async function videosMatchingText(config: ServiceConfiguration, text: string): Promise<Set<string> | null> {
  if (!config.agentUrl) return null;
  try {
    const hits = await new AgentRevisionSearchRepository(config.agentUrl, AbortSignal.timeout(REVISION_SEARCH_TIMEOUT_MS)).search({
      query: text,
      topK: REVISION_TOP_K,
    });
    return hits.length ? new Set(hits.map((hit) => hit.videoId)) : null;
  } catch {
    return null;
  }
}

/** The incidents the other filters allow, narrowed to the ones the agent matched; the sort is kept. */
async function listMatchingIncidents(
  incidents: IncidentRepository,
  query: Omit<ReportListQuery, 'page' | 'pageSize' | 'search'>,
  videoIds: Set<string>,
  page: number,
  pageSize: number,
): Promise<ReportList> {
  const all = await incidents.listReports({ ...query, search: null, page: 1, pageSize: MAX_LIST_SIZE });
  const matched = all.items.filter((item) => videoIds.has(item.videoId));
  return { items: matched.slice((page - 1) * pageSize, page * pageSize), totalItems: matched.length, incidentTypes: all.incidentTypes };
}

export async function GET(request: Request) {
  try {
    const config = getServiceConfiguration();
    const { incidents } = getDbAdapters(config);

    const params = new URL(request.url).searchParams;
    const requestedPage = Number.parseInt(params.get('page') || '1', 10);
    const page = Number.isFinite(requestedPage) && requestedPage > 0 ? requestedPage : 1;
    const pageSize = params.get('all') === 'true' ? 1000 : PAGE_SIZE;
    const sort = params.get('sort') || 'newest';
    const severity = params.get('severity') || 'all';
    const dayRaw = params.get('day');
    const dayOfWeek = dayRaw === null ? null : Number(dayRaw);
    const tzParam = params.get('timezone');
    if (tzParam !== null && !isValidTimeZone(tzParam)) return NextResponse.json({ error: 'Invalid report timezone' }, { status: 400 });
    const timezone = tzParam || 'UTC';
    const kind = optional(params, 'kind');
    if (kind !== null && kind !== 'ai' && kind !== 'human') return NextResponse.json({ error: 'Invalid revision kind' }, { status: 400 });
    const scope = params.get('scope') || 'all';
    const match = params.get('match') || 'contains';
    const entityTypes = [
      ...new Set(
        params
          .getAll('entityType')
          .map((value) => value.trim().toLowerCase())
          .filter(Boolean),
      ),
    ];
    if (!isSort(sort)) return NextResponse.json({ error: 'Invalid report sort' }, { status: 400 });
    if (!isScope(scope)) return NextResponse.json({ error: 'Invalid report scope' }, { status: 400 });
    if (!isMatch(match)) return NextResponse.json({ error: 'Invalid evidence match' }, { status: 400 });
    if (entityTypes.some((value) => !ENTITY_TYPES.has(value))) return NextResponse.json({ error: 'Invalid entity type' }, { status: 400 });
    if (!SEVERITIES.has(severity)) return NextResponse.json({ error: 'Invalid report severity' }, { status: 400 });
    if (dayOfWeek !== null && (!Number.isInteger(dayOfWeek) || dayOfWeek < 0 || dayOfWeek > 6))
      return NextResponse.json({ error: 'Invalid report weekday' }, { status: 400 });

    const search = optional(params, 'search');
    const filters: Omit<ReportListQuery, 'page' | 'pageSize' | 'search'> = {
      type: optional(params, 'type'),
      severity: optional(params, 'severity'),
      kind,
      generatedAfter: optional(params, 'after'),
      generatedBefore: optional(params, 'before'),
      timeFrom: optional(params, 'fromTime'),
      timeTo: optional(params, 'toTime'),
      entities: evidenceFilters(params, 'entity'),
      instruments: evidenceFilters(params, 'instrument'),
      assets: evidenceFilters(params, 'asset'),
      dayOfWeek,
      sort,
      scope,
      entityTypes: entityTypes.length ? entityTypes : null,
      evidenceMatch: match,
      timezone,
    };
    const videoIds = search === null ? null : await videosMatchingText(config, search);
    const {
      items: summaries,
      totalItems,
      incidentTypes,
    } = videoIds
      ? await listMatchingIncidents(incidents, filters, videoIds, page, pageSize)
      : await incidents.listReports({ ...filters, search, page, pageSize });
    const sign = async (key: string) => {
      try {
        return await createR2PlaybackUrl(config, key);
      } catch {
        return undefined;
      }
    };
    const reports =
      params.get('all') === 'true'
        ? summaries
        : await Promise.all(
            summaries.map(async (report) => {
              // Only the video's screenshot is signed: a card shows MVP1's skeleton when it is missing, never an evidence crop.
              const thumbnailUrl = isValidR2Key(report.r2Key) ? await sign(thumbnailKeyForVideo(report.r2Key)) : undefined;
              return { ...report, ...(thumbnailUrl ? { thumbnailUrl } : {}) };
            }),
          );

    return NextResponse.json({
      reports,
      incidentTypes,
      /** With text: 'semantic' when the agent ranked it, 'text' for the store's ILIKE filter. */
      ...(search === null ? {} : { searchMode: videoIds ? 'semantic' : 'text' }),
      pagination: {
        page,
        pageSize,
        totalItems,
        totalPages: Math.ceil(totalItems / pageSize),
      },
    });
  } catch (error) {
    if (error instanceof RangeError) return NextResponse.json({ error: error.message }, { status: 400 });
    return errorResponse(error, 'Could not load reports');
  }
}
