// SPDX-License-Identifier: Apache-2.0

// EvidenceObjectStore over Cloudflare R2, using the console's R2 configuration.

import type { ServiceConfiguration } from '@/lib/env';
import { deleteR2Video } from '@/lib/r2/config';
import { listR2Objects } from '@/lib/r2/list';
import type { EvidenceObjectStore, StoredObject } from '@/modules/reports/application/types';

export class R2EvidenceObjectStore implements EvidenceObjectStore {
  private readonly config: ServiceConfiguration;

  constructor(config: ServiceConfiguration) {
    this.config = config;
  }

  list(prefix: string): Promise<StoredObject[]> {
    return listR2Objects(this.config, prefix);
  }

  remove(key: string): Promise<void> {
    return deleteR2Video(this.config, key);
  }
}
