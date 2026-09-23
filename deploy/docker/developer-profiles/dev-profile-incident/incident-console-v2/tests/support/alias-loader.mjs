// SPDX-License-Identifier: Apache-2.0

// Minimal resolver so plain `node --test` can execute the project's real
// `.ts` sources (which use the `@/*` -> project-root TS path alias from
// tsconfig.json) without pulling in a bundler. Node's ESM resolver has no
// concept of tsconfig `paths`, so tests that need to exercise real route/lib
// code (not just read it as text) must supply this mapping themselves.

import { existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';

const projectRoot = new URL('../../', import.meta.url);

export async function resolve(specifier, context, nextResolve) {
  if (specifier === 'next/server') {
    return nextResolve('next/server.js', context);
  }
  if (specifier.startsWith('@/')) {
    const rest = specifier.slice(2);
    for (const ext of ['.ts', '.tsx']) {
      const candidate = new URL(`${rest}${ext}`, projectRoot);
      if (existsSync(fileURLToPath(candidate))) {
        return nextResolve(candidate.href, context);
      }
    }
  }
  return nextResolve(specifier, context);
}
