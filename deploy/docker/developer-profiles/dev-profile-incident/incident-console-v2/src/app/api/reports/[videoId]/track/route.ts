// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { getEvidenceTrack } from '@/modules/reports/application/get-evidence-track';
import type { EvidenceItemType } from '@/modules/reports/domain/revision';

export const dynamic = 'force-dynamic';
export const maxDuration = 30;

const ITEM_TYPES: readonly string[] = ['entity', 'instrument', 'asset'];
/** A track holds at most 5 samples a second of about 50 bytes each; anything this large is not one. */
const MAX_TRACK_BYTES = 4 * 1024 * 1024;

/**
 * One item's track samples, ?revision=<id>&type=<entity|instrument|asset>&item=<id>, as {samples: [{t, box}]}. The track is
 * read from R2 on the server because R2 has no CORS rule for the console origin. 400 for a malformed query, 404 when the
 * revision or its entry has no track, 502 when the stored file cannot be read. Errors never name the key or a signed URL.
 */
export async function GET(request: Request, context: { params: Promise<{ videoId: string }> }) {
  const { videoId } = await context.params;
  const query = new URL(request.url).searchParams;
  const revisionId = Number(query.get('revision'));
  const itemType = query.get('type') ?? '';
  const itemId = query.get('item') ?? '';
  if (!Number.isSafeInteger(revisionId) || revisionId < 1 || !ITEM_TYPES.includes(itemType) || !itemId) {
    return NextResponse.json({ error: 'revision, type and item are required' }, { status: 400 });
  }
  const config = getServiceConfiguration();
  const read = async (key: string) => {
    const response = await fetch(await createR2PlaybackUrl(config, key), { cache: 'no-store' });
    if (!response.ok) throw new TrackReadError(`The stored track returned HTTP ${response.status}`);
    const body = await response.text();
    if (body.length > MAX_TRACK_BYTES) throw new TrackReadError('The stored track is too large');
    try {
      return JSON.parse(body) as unknown;
    } catch {
      return null;
    }
  };
  try {
    const samples = await getEvidenceTrack(getDbAdapters(config).incidents, read, {
      videoId,
      revisionId,
      itemType: itemType as EvidenceItemType,
      itemId,
    });
    if (!samples) return NextResponse.json({ error: 'This item has no track' }, { status: 404 });
    return NextResponse.json({ samples }, { headers: { 'Cache-Control': 'private, max-age=300' } });
  } catch (error) {
    const message = error instanceof TrackReadError ? error.message : 'Could not read the track';
    return NextResponse.json({ error: message }, { status: 502 });
  }
}

class TrackReadError extends Error {}
