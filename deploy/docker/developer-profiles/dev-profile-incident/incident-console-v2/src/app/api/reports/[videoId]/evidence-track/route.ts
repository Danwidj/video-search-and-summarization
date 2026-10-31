// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { getServiceConfiguration, isR2Configured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { isValidR2Key } from '@/lib/r2/key';
import { isEvidenceKeyOfVideo } from '@/modules/reports/domain/revision';

export const dynamic = 'force-dynamic';
export const maxDuration = 30;
/** A track holds at most five samples a second, about 60 bytes each: 2 MB is well over an hour. */
const MAX_TRACK_BYTES = 2 * 1024 * 1024;

/**
 * A person track file of the video (?key=evidence/<video key>/run-<n>/<itemId>-track.json) as stored, for Edit mode's
 * track scrubber. Read on the server because R2 has no CORS rule for the console origin, so the browser cannot fetch
 * the signed URL itself. 400 for a key that is not a track of this video, 404 for an unknown video or a missing file,
 * 502 for a file that is too large or not JSON. The client checks the samples (lib/evidence/track.ts).
 */
export async function GET(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const key = new URL(request.url).searchParams.get('key') ?? '';
    const config = getServiceConfiguration();
    if (!isR2Configured(config)) throw new Error('R2 is not configured');
    const video = await getDbAdapters(config).videos.getVideo(videoId);
    if (!isValidR2Key(video?.storageKey)) return NextResponse.json({ error: 'Video not found' }, { status: 404 });
    if (!isValidR2Key(key) || !key.endsWith('-track.json') || !isEvidenceKeyOfVideo(key, video.storageKey)) {
      return NextResponse.json({ error: 'The key must name a track file of this video' }, { status: 400 });
    }
    const response = await fetch(await createR2PlaybackUrl(config, key), { cache: 'no-store' });
    if (response.status === 404) return NextResponse.json({ error: 'Track not found' }, { status: 404 });
    if (!response.ok) return NextResponse.json({ error: `The track could not be read (${response.status})` }, { status: 502 });
    const text = await response.text();
    if (text.length > MAX_TRACK_BYTES) return NextResponse.json({ error: 'The track file is too large' }, { status: 502 });
    let samples: unknown;
    try {
      samples = JSON.parse(text);
    } catch {
      return NextResponse.json({ error: 'The track file is not JSON' }, { status: 502 });
    }
    return NextResponse.json(samples, { headers: { 'Cache-Control': 'private, max-age=300' } });
  } catch (error) {
    return errorResponse(error, 'Could not read the track');
  }
}
