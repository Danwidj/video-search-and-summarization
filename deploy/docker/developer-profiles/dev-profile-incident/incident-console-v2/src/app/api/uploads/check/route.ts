// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getServiceConfiguration, isR2Configured } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { r2ObjectExists } from '@/lib/r2/config';
import { firstFreeName, inspectUploadName, uploadKeyForName } from '@/lib/r2/names';

/**
 * Pre-upload check of a file name. Returns the name the file would be stored
 * under, the characters that had to be replaced, whether the name was
 * shortened, and whether the name is already taken (`name` is then the next
 * free `name-2.ext`). Nothing is written.
 */
export async function POST(request: Request) {
  try {
    const body = (await request.json().catch(() => null)) as { filename?: unknown } | null;
    if (typeof body?.filename !== 'string' || !body.filename.trim()) {
      return NextResponse.json({ error: 'filename is required' }, { status: 400 });
    }
    const config = getServiceConfiguration();
    if (!isR2Configured(config)) throw new Error('R2 is not configured');
    const checked = inspectUploadName(body.filename);
    const name = await firstFreeName(checked.name, (candidate) => r2ObjectExists(config, uploadKeyForName(candidate)));
    return NextResponse.json({
      name,
      key: uploadKeyForName(name),
      unsafeChars: checked.unsafeChars,
      truncated: checked.truncated,
      exists: name !== checked.name,
      existingName: checked.name,
    });
  } catch (error) {
    return errorResponse(error, 'Could not check the file name');
  }
}
