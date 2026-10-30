// SPDX-License-Identifier: Apache-2.0

import { Readable } from 'node:stream';

import { NextResponse } from 'next/server';

import { getDbAdapters, getIncidentVideos } from '@/lib/container';
import { getServiceConfiguration, isR2Configured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { createR2PlaybackUrl, putR2Video, r2ObjectExists, verifyR2Video } from '@/lib/r2/config';
import { isValidR2Key } from '@/lib/r2/key';
import { parseIncidentId } from '@/modules/reports/domain/incident-id';
import { uploadedEvidenceKey } from '@/modules/reports/domain/revision';

export const dynamic = 'force-dynamic';

export const maxDuration = 30;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
// Stored under a .jpg key; the content type is the file's own.
const IMAGE_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
const ITEM_ID = /^[A-Za-z0-9_-]{1,64}$/;

/**
 * Stores a replacement evidence image under a new R2 key
 * (evidence/<video key>/edit-<n>/<itemId>.jpg for the camera `video` of the incident, the first n whose key is free). It never overwrites an object, and
 * nothing deletes one here: any revision may still reference it. Only the evidence-sweep route removes an image, and only one no revision names. The key is saved
 * into the next human revision's evidence by Save.
 */
export async function POST(request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const incidentId = parseIncidentId((await context.params).incidentId);
    if (incidentId === null) return NextResponse.json({ error: 'The incident id must be a positive integer' }, { status: 400 });
    const form = await request.formData();
    const file = form.get('file');
    const itemId = form.get('itemId');
    const videoName = form.get('video');
    if (
      !(file instanceof Blob) ||
      typeof itemId !== 'string' ||
      !ITEM_ID.test(itemId) ||
      typeof videoName !== 'string' ||
      !videoName.trim()
    ) {
      return NextResponse.json({ error: 'file, a valid itemId and video are required' }, { status: 400 });
    }
    if (!IMAGE_TYPES.has(file.type)) return NextResponse.json({ error: 'The image must be JPEG, PNG or WebP' }, { status: 415 });
    if (file.size <= 0 || file.size > MAX_IMAGE_BYTES)
      return NextResponse.json({ error: 'The image must be between 1 byte and 5 MB' }, { status: 413 });

    const config = getServiceConfiguration();
    if (!isR2Configured(config)) throw new Error('R2 is not configured');
    const video = await getIncidentVideos(config).getVideo(videoName.trim());
    if (video?.incidentId !== incidentId || !isValidR2Key(video.storageKey))
      return NextResponse.json({ error: 'Video not found' }, { status: 404 });
    let editNumber = 1;
    while (await r2ObjectExists(config, uploadedEvidenceKey(video.storageKey, editNumber, itemId))) editNumber += 1;
    const key = uploadedEvidenceKey(video.storageKey, editNumber, itemId);
    const body = Readable.fromWeb(file.stream() as Parameters<typeof Readable.fromWeb>[0]);
    await putR2Video(config, key, body, file.type, file.size);
    await verifyR2Video(config, key, file.size);
    return NextResponse.json({ image: key });
  } catch (error) {
    return errorResponse(error, 'Could not upload the evidence image');
  }
}

/**
 * A short-lived URL for one evidence image: ?video=<file name of the covering video>&image=<R2 key>. The image must be
 * one the video's stored records can still show (a revision's evidence or a crop of that video), so a key cannot be
 * signed through another video or incident. 404 when the incident, the video or the image is not found.
 */
export async function GET(request: Request, context: { params: Promise<{ incidentId: string }> }) {
  try {
    const incidentId = parseIncidentId((await context.params).incidentId);
    if (incidentId === null) return NextResponse.json({ error: 'The incident id must be a positive whole number' }, { status: 400 });
    const params = new URL(request.url).searchParams;
    const video = params.get('video')?.trim();
    const image = params.get('image');
    if (!video || !image) return NextResponse.json({ error: 'video and image are required' }, { status: 400 });

    const config = getServiceConfiguration();
    if (!isR2Configured(config)) throw new Error('R2 is not configured');
    const referenced = await getDbAdapters(config).incidentReports.listReferencedEvidenceImages(incidentId, video);
    if (!referenced?.includes(image)) return NextResponse.json({ error: 'Evidence image not found' }, { status: 404 });
    return NextResponse.json({ url: await createR2PlaybackUrl(config, image) });
  } catch (error) {
    return errorResponse(error, 'Could not read the evidence image');
  }
}
