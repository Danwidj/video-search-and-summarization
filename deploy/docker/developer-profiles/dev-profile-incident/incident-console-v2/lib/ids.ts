// SPDX-License-Identifier: Apache-2.0

import { createHash } from 'node:crypto';

export function compactId(prefix: string, value: string): string {
  return prefix + createHash('sha256').update(value).digest('hex').slice(0, 19);
}
