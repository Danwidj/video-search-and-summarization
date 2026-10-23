// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { StoreRejection } from '@/modules/shared/domain/common';

export function errorResponse(error: unknown, fallback: string): NextResponse {
  const message = error instanceof Error ? error.message : fallback;
  return NextResponse.json({ error: message }, { status: 500 });
}

/** A domain refusal from the store as 404 or 422; null for any other error. */
export function rejectionResponse(error: unknown): NextResponse | null {
  if (!(error instanceof StoreRejection)) return null;
  return NextResponse.json({ error: error.message }, { status: error.reason === 'not-found' ? 404 : 422 });
}

export async function readUpstream(response: Response, label: string): Promise<unknown> {
  const text = await response.text();
  if (!response.ok) throw new Error(`${label} returned HTTP ${response.status}: ${text.slice(0, 400)}`);
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error(`${label} returned an invalid JSON response`);
  }
}
