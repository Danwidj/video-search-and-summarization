// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { errorResponse } from '@/lib/http';
import type { VideoListFilter } from '@/lib/ports/videos';

export const dynamic = 'force-dynamic';

const PAGE_SIZE = 20;
const FILTERS = new Set(['all', 'without-report', 'awaiting-selection']);

/**
 * Videos (the parent of every analysis). `filter=without-report` lists videos
 * that have no successful analysis at all, e.g. uploads whose analyses all
 * failed, so they stay discoverable and can be analysed again.
 */
export async function GET(request: Request) {
  try {
    const params = new URL(request.url).searchParams;
    const filter = params.get('filter') || 'all';
    if (!FILTERS.has(filter)) return NextResponse.json({ error: 'Invalid video filter' }, { status: 400 });
    const page = Math.max(1, Number.parseInt(params.get('page') || '1', 10) || 1);
    const { videos } = getDbAdapters();
    const { items, totalItems } = await videos.listVideos(filter as VideoListFilter, page, PAGE_SIZE);
    return NextResponse.json({ videos: items, pagination: { page, pageSize: PAGE_SIZE, totalItems, totalPages: Math.ceil(totalItems / PAGE_SIZE) }, filter });
  } catch (error) {
    return errorResponse(error, 'Could not load videos');
  }
}
