// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters, getEvidenceClipStore } from '@/lib/container';
import { r2FrameConfiguration } from '@/lib/r2/frame-source';
import { getEvidenceClip } from '@/modules/reports/application/get-evidence-clip';
import { ClipError } from '@/modules/reports/domain/evidence-clip';
import type { EvidenceItemType } from '@/modules/reports/domain/revision';

export const dynamic = 'force-dynamic';
export const maxDuration = 60;

const ITEM_TYPES: readonly string[] = ['entity', 'instrument', 'asset'];
const ITEM_ID = /^[A-Za-z0-9_-]{1,64}$/;

/**
 * One item's evidence clip, ?revision=<id>&type=<entity|instrument|asset>&item=<id>, as {url}: a short-lived signed URL of
 * about 4 seconds of the video around the item's second (H.264 MP4, no audio). The first request cuts it with ffmpeg and
 * stores it in R2 beside the item's evidence (<folder>/<itemId>-clip.mp4); later requests sign the stored clip. 400 for a
 * malformed query, 404 for an unknown version or item, 409 when the video file is missing, 422 when the item has no second
 * or no evidence folder, 502 when ffmpeg fails, 503 when it is not installed. Errors never name a key or a signed URL.
 */
export async function POST(request: Request, context: { params: Promise<{ videoId: string }> }) {
  const { videoId } = await context.params;
  const query = new URL(request.url).searchParams;
  const revisionId = Number(query.get('revision'));
  const itemType = query.get('type') ?? '';
  const itemId = query.get('item') ?? '';
  if (!Number.isSafeInteger(revisionId) || revisionId < 1 || !ITEM_TYPES.includes(itemType) || !ITEM_ID.test(itemId)) {
    return NextResponse.json({ error: 'revision, type and item are required' }, { status: 400 });
  }
  try {
    const config = r2FrameConfiguration();
    const url = await getEvidenceClip(getDbAdapters(config).incidents, getEvidenceClipStore(config), {
      videoId,
      revisionId,
      itemType: itemType as EvidenceItemType,
      itemId,
    });
    return NextResponse.json({ url }, { headers: { 'Cache-Control': 'no-store' } });
  } catch (error) {
    if (error instanceof ClipError) return NextResponse.json({ error: error.message }, { status: error.status });
    return NextResponse.json({ error: 'Could not prepare the clip' }, { status: 500 });
  }
}
