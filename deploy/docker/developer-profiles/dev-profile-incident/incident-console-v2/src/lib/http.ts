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

/** An upstream service answered with an error status; `status` lets a route pass a 4xx on. */
export class UpstreamError extends Error {
  readonly status: number;
  /** The upstream's own response text, for a route that shows only part of it. */
  readonly body: string;

  constructor(message: string, status: number, body = '') {
    super(message);
    this.name = 'UpstreamError';
    this.status = status;
    this.body = body;
  }
}

export async function readUpstream(response: Response, label: string): Promise<unknown> {
  const text = await response.text();
  if (!response.ok) throw new UpstreamError(`${label} returned HTTP ${response.status}: ${text.slice(0, 400)}`, response.status, text);
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    throw new Error(`${label} returned an invalid JSON response`);
  }
}
