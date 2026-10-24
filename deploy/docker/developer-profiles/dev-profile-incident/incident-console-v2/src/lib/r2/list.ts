// SPDX-License-Identifier: Apache-2.0

// Listing lives apart from config.ts so the routes that never list do not load ListObjectsV2Command.

import type { ServiceConfiguration } from '@/lib/env';
import { createR2Configuration } from '@/lib/r2/config';
import { isValidR2Key } from '@/lib/r2/key';
import { ListObjectsV2Command, S3Client } from '@aws-sdk/client-s3';

/** Every object whose key starts with `prefix`, across all pages of the listing. */
export async function listR2Objects(
  config: ServiceConfiguration,
  prefix: string,
): Promise<Array<{ key: string; lastModified: Date | null }>> {
  const r2 = createR2Configuration(config);
  if (!r2) throw new Error('R2 is not configured');
  if (!isValidR2Key(prefix)) throw new Error('Invalid R2 key prefix');
  const client = new S3Client({
    region: 'auto',
    endpoint: r2.endpoint,
    credentials: { accessKeyId: r2.accessKeyId, secretAccessKey: r2.secretAccessKey },
  });
  const objects: Array<{ key: string; lastModified: Date | null }> = [];
  let token: string | undefined;
  do {
    const page = await client.send(new ListObjectsV2Command({ Bucket: r2.bucket, Prefix: prefix, ContinuationToken: token }));
    for (const object of page.Contents ?? []) {
      if (object.Key) objects.push({ key: object.Key, lastModified: object.LastModified ?? null });
    }
    token = page.IsTruncated ? page.NextContinuationToken : undefined;
    if (page.IsTruncated && !token) throw new Error('R2 listing was cut short');
  } while (token);
  return objects;
}
