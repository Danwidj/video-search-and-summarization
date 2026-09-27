// SPDX-License-Identifier: Apache-2.0

import type { Readable } from 'node:stream';

import type { ServiceConfiguration } from '@/lib/env';
import { isValidR2Key } from '@/lib/r2/key';
import { mp4DurationSeconds } from '@/lib/video/mp4-duration';
import { DeleteObjectCommand, GetObjectCommand, HeadObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

// Cloudflare R2's limit for a single (non-multipart) PutObject.
export const MAX_R2_PUT_BYTES = 5 * 1024 ** 3;

export interface R2Configuration {
  endpoint: string;
  bucket: string;
  accessKeyId: string;
  secretAccessKey: string;
}

export function createR2Configuration(config: ServiceConfiguration): R2Configuration | null {
  if (!config.r2AccountId || !config.r2Bucket || !config.r2AccessKey || !config.r2SecretKey) return null;

  return {
    endpoint: `https://${config.r2AccountId}.r2.cloudflarestorage.com`,
    bucket: config.r2Bucket,
    accessKeyId: config.r2AccessKey,
    secretAccessKey: config.r2SecretKey,
  };
}

export async function createR2PlaybackUrl(config: ServiceConfiguration, key: string): Promise<string> {
  const r2 = createR2Configuration(config);
  if (!r2) throw new Error('R2 is not configured');
  if (!isValidR2Key(key)) throw new Error('Invalid R2 object key');

  const client = new S3Client({
    region: 'auto',
    endpoint: r2.endpoint,
    credentials: { accessKeyId: r2.accessKeyId, secretAccessKey: r2.secretAccessKey },
  });
  return getSignedUrl(
    client,
    new GetObjectCommand({ Bucket: r2.bucket, Key: key, ResponseContentDisposition: 'inline' }),
    { expiresIn: 3600 },
  );
}

export async function verifyR2Video(
  config: ServiceConfiguration,
  key: string,
  expectedContentLength?: number,
): Promise<{ contentLength: number }> {
  const r2 = createR2Configuration(config);
  if (!r2) throw new Error('R2 is not configured');
  if (!isValidR2Key(key)) throw new Error('Invalid R2 object key');

  const client = new S3Client({
    region: 'auto',
    endpoint: r2.endpoint,
    credentials: { accessKeyId: r2.accessKeyId, secretAccessKey: r2.secretAccessKey },
  });
  const result = await client.send(new HeadObjectCommand({ Bucket: r2.bucket, Key: key }));
  const contentLength = result.ContentLength;
  if (typeof contentLength !== 'number' || contentLength <= 0) {
    throw new Error('R2 object is empty or has no content length');
  }
  if (expectedContentLength !== undefined && contentLength !== expectedContentLength) {
    throw new Error(`R2 object size mismatch: expected ${expectedContentLength} bytes, found ${contentLength}`);
  }
  return { contentLength };
}

export async function putR2Video(
  config: ServiceConfiguration,
  key: string,
  body: Readable,
  contentType: string,
  contentLength: number,
): Promise<void> {
  const r2 = createR2Configuration(config);
  if (!r2) throw new Error('R2 is not configured');
  if (!isValidR2Key(key)) throw new Error('Invalid R2 object key');
  if (contentLength > MAX_R2_PUT_BYTES) throw new Error('Video exceeds the R2 single-upload size limit');

  const client = new S3Client({
    region: 'auto',
    endpoint: r2.endpoint,
    credentials: { accessKeyId: r2.accessKeyId, secretAccessKey: r2.secretAccessKey },
  });
  await client.send(
    new PutObjectCommand({ Bucket: r2.bucket, Key: key, Body: body, ContentType: contentType, ContentLength: contentLength }),
  );
}

export async function deleteR2Video(config: ServiceConfiguration, key: string): Promise<void> {
  const r2 = createR2Configuration(config);
  if (!r2) throw new Error('R2 is not configured');
  if (!isValidR2Key(key)) throw new Error('Invalid R2 object key');
  const client = new S3Client({
    region: 'auto',
    endpoint: r2.endpoint,
    credentials: { accessKeyId: r2.accessKeyId, secretAccessKey: r2.secretAccessKey },
  });
  await client.send(new DeleteObjectCommand({ Bucket: r2.bucket, Key: key }));
}

/**
 * The video's length in seconds from its MP4 header, read with ranged GETs
 * (lib/video/mp4-duration.ts). null when it cannot be read: validation then
 * records the video-length rule as not checked, never as passed.
 */
export async function readR2VideoDurationSeconds(config: ServiceConfiguration, key: string, contentLength: number): Promise<number | null> {
  const r2 = createR2Configuration(config);
  if (!r2 || !isValidR2Key(key)) return null;
  const client = new S3Client({
    region: 'auto',
    endpoint: r2.endpoint,
    credentials: { accessKeyId: r2.accessKeyId, secretAccessKey: r2.secretAccessKey },
  });
  const readRange = async (offset: number, length: number): Promise<Uint8Array> => {
    const end = Math.min(offset + length, contentLength) - 1;
    if (end < offset) return new Uint8Array(0);
    const result = await client.send(new GetObjectCommand({ Bucket: r2.bucket, Key: key, Range: `bytes=${offset}-${end}` }));
    return result.Body ? await result.Body.transformToByteArray() : new Uint8Array(0);
  };
  try {
    return await mp4DurationSeconds(readRange, contentLength);
  } catch {
    return null;
  }
}
