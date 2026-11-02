// SPDX-License-Identifier: Apache-2.0

// The box tool's two calls to the console's proxy routes (contract: POST /api/reports/[videoId]/box/describe and /box/track).
// Kept in this one small module so the routes' owner can change how they are called without touching the dialog.

import { parseDescribeResponse, parseTrackResponse } from '@/lib/evidence/box-tool';
import type { Box, BoxItemType, BoxProposal, ReviewerTrack } from '@/modules/reports/domain/box-item';

export interface DescribeRequest {
  seconds: number;
  box: Box;
}

export interface TrackRequest {
  seconds: number;
  box: Box;
  itemType: BoxItemType;
  name: string;
  description: string;
  backSeconds?: number;
  forwardSeconds?: number;
}

export interface BoxToolClient {
  describe(
    videoId: string,
    request: DescribeRequest,
    signal?: AbortSignal,
  ): Promise<{ proposal: BoxProposal | null; reason: string | null }>;
  track(videoId: string, request: TrackRequest, signal?: AbortSignal): Promise<ReviewerTrack | null>;
}

async function post(videoId: string, route: 'describe' | 'track', body: unknown, signal?: AbortSignal): Promise<unknown> {
  const response = await fetch(`/api/reports/${encodeURIComponent(videoId)}/box/${route}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  });
  const json = await response.json().catch(() => null);
  if (!response.ok) throw new Error((json as { error?: string } | null)?.error ?? `The ${route} request failed (${response.status})`);
  return json;
}

export const boxToolClient: BoxToolClient = {
  async describe(videoId, request, signal) {
    return parseDescribeResponse(await post(videoId, 'describe', request, signal));
  },
  async track(videoId, request, signal) {
    return parseTrackResponse(await post(videoId, 'track', request, signal));
  },
};
