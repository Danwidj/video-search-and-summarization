// SPDX-License-Identifier: Apache-2.0

// Edge-only: the answer to a repeat upload, shared by the upload and job routes.

import { NextResponse } from 'next/server';

import type { DuplicateUploadError } from '@/modules/uploads/domain/duplicate';

/** HTTP 409 with the message and where the same content already is, for the upload page to link. */
export function duplicateResponse(error: DuplicateUploadError): NextResponse {
  return NextResponse.json({ error: error.message, duplicate: error.duplicate }, { status: 409 });
}
