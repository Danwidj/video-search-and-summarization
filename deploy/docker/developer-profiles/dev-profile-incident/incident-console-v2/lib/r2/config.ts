// SPDX-License-Identifier: Apache-2.0

import type { ServiceConfiguration } from '@/lib/env';
import { DeleteObjectCommand, GetObjectCommand, PutObjectCommand, S3Client } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';

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
  if (!key || key.startsWith('/') || key.includes('..')) throw new Error('Invalid R2 object key');

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

export async function putR2Video(
  config: ServiceConfiguration,
  key: string,
  body: Uint8Array,
  contentType: string,
): Promise<void> {
  const r2 = createR2Configuration(config);
  if (!r2) throw new Error('R2 is not configured');
  if (!key || key.startsWith('/') || key.includes('..')) throw new Error('Invalid R2 object key');

  const client = new S3Client({
    region: 'auto',
    endpoint: r2.endpoint,
    credentials: { accessKeyId: r2.accessKeyId, secretAccessKey: r2.secretAccessKey },
  });
  await client.send(new PutObjectCommand({ Bucket: r2.bucket, Key: key, Body: body, ContentType: contentType }));
}

export async function deleteR2Video(config: ServiceConfiguration, key: string): Promise<void> {
  const r2 = createR2Configuration(config);
  if (!r2) throw new Error('R2 is not configured');
  if (!key || key.startsWith('/') || key.includes('..')) throw new Error('Invalid R2 object key');
  const client = new S3Client({
    region: 'auto',
    endpoint: r2.endpoint,
    credentials: { accessKeyId: r2.accessKeyId, secretAccessKey: r2.secretAccessKey },
  });
  await client.send(new DeleteObjectCommand({ Bucket: r2.bucket, Key: key }));
}
