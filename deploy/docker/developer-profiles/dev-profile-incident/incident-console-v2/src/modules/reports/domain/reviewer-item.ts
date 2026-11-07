// SPDX-License-Identifier: Apache-2.0

// A reviewer's item from the box tool (or an existing item the reviewer re-tracked): the AI proposal for a boxed region, the
// track the agent made from the box, and the rules that turn them into the evidence entry Save stores. Browser-safe, no I/O.
// Shapes follow the shared contract (vss-evidence-box-contract.md): camelCase here, snake_case on the agent and in storage.

import type { TrackSample } from '@/modules/reports/domain/track';
import type { EvidenceItemType } from '@/modules/reports/domain/revision';

export type Box = [number, number, number, number];

/** The model's reading of a boxed region (POST box/describe), kept as returned for audit. */
export interface BoxProposal {
  itemType: EvidenceItemType;
  name: string;
  description: string;
  holder: string | null;
  threatLevel: number | null;
  confidence: number;
}

export interface BoxDescribeResult {
  proposal: BoxProposal | null;
  reason: string | null;
}

/** A track made from the reviewer's box (POST box/track). `samples` use the AI track sample shape, plus a per-sample confidence. */
export interface ReviewerTrack {
  source: 'reviewer';
  samples: Array<TrackSample & { conf?: number }>;
  span: [number, number];
  partial: boolean;
  lostAt: number | null;
  reason?: string | null;
}

/** What the box tool hands the draft for one item; `track` null means a still image taken at `stillSeconds` in `stillBox`. */
export interface ReviewerDraftItem {
  itemType: EvidenceItemType;
  name: string;
  description: string;
  holder?: string | null;
  threatLevel?: number | null;
  /** A new entity's kind, chosen by the reviewer (never unknown). */
  entityType?: 'human' | 'animal';
  aiProposal: BoxProposal | null;
  track: ReviewerTrack | null;
  stillSeconds?: number;
  stillBox?: Box;
}

export class ReviewerItemError extends Error {}

/** The box and second an item's evidence image is cut from: the track's first sample, or the still image's own. */
export function firstSeen(item: Pick<ReviewerDraftItem, 'track' | 'stillSeconds' | 'stillBox'>): { seconds: number; box: Box } {
  const first = item.track?.samples[0];
  if (first) return { seconds: first.t, box: first.box };
  if (item.stillSeconds !== undefined && item.stillBox) return { seconds: item.stillSeconds, box: item.stillBox };
  throw new ReviewerItemError('A reviewer item needs a track or a still second and box');
}

/** The track file stored at `edit-<N>/<itemId>-track.json`: the AI track's samples, with the reviewer markers. */
export function trackFileOf(track: ReviewerTrack): {
  source: 'reviewer';
  samples: ReviewerTrack['samples'];
  span: [number, number];
  partial: boolean;
  lost_at: number | null;
  reason: string | null;
} {
  return {
    source: 'reviewer',
    samples: track.samples,
    span: track.span,
    partial: track.partial,
    lost_at: track.lostAt,
    reason: track.reason ?? null,
  };
}

const isNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const isBox = (value: unknown): value is Box =>
  Array.isArray(value) && value.length === 4 && value.every((n) => isNumber(n) && n >= 0 && n <= 1000);

/** A track from JSON (agent answer or a Save body): null when not a usable reviewer track. */
export function parseReviewerTrack(raw: unknown): ReviewerTrack | null {
  if (!raw || typeof raw !== 'object') return null;
  const body = raw as Record<string, unknown>;
  if (!Array.isArray(body.samples)) return null;
  const samples: ReviewerTrack['samples'] = [];
  for (const entry of body.samples) {
    const sample = (entry && typeof entry === 'object' ? entry : {}) as Record<string, unknown>;
    if (!isNumber(sample.t) || sample.t < 0 || !isBox(sample.box)) return null;
    samples.push({ t: sample.t, box: sample.box, ...(isNumber(sample.conf) ? { conf: sample.conf } : {}) });
  }
  if (!samples.length) return null;
  samples.sort((a, b) => a.t - b.t);
  const lostAt = isNumber(body.lostAt) ? body.lostAt : isNumber(body.lost_at) ? body.lost_at : null;
  return {
    source: 'reviewer',
    samples,
    span: [samples[0].t, samples[samples.length - 1].t],
    partial: body.partial === true,
    lostAt,
    reason: typeof body.reason === 'string' ? body.reason : null,
  };
}

/** The agent's `proposal` object (snake_case) -> BoxProposal; null when absent or malformed. */
export function parseBoxProposal(raw: unknown): BoxProposal | null {
  if (!raw || typeof raw !== 'object') return null;
  const body = raw as Record<string, unknown>;
  const type = body.itemType ?? body.item_type;
  if (type !== 'entity' && type !== 'instrument' && type !== 'asset') return null;
  if (typeof body.name !== 'string' || !body.name.trim()) return null;
  const threat = body.threatLevel ?? body.threat_level;
  return {
    itemType: type,
    name: body.name,
    description: typeof body.description === 'string' ? body.description : '',
    holder: typeof body.holder === 'string' && body.holder ? body.holder : null,
    threatLevel: isNumber(threat) ? threat : null,
    confidence: isNumber(body.confidence) ? body.confidence : 0,
  };
}

/** A proposal back to the snake_case it is stored in (evidence entry `ai_proposal`). */
export function proposalRecord(proposal: BoxProposal): Record<string, unknown> {
  return {
    item_type: proposal.itemType,
    name: proposal.name,
    description: proposal.description,
    holder: proposal.holder,
    threat_level: proposal.threatLevel,
    confidence: proposal.confidence,
  };
}

/** What Save sends for a reviewer item: the part of the draft item the server stores (the server cuts the images itself). */
export interface ReviewerPayload {
  ai_proposal: Record<string, unknown> | null;
  track: ReturnType<typeof trackFileOf> | null;
  still_seconds: number | null;
  still_box: Box | null;
}

export function reviewerPayload(item: ReviewerDraftItem): ReviewerPayload {
  const seen = firstSeen(item);
  return {
    ai_proposal: item.aiProposal ? proposalRecord(item.aiProposal) : null,
    track: item.track ? trackFileOf(item.track) : null,
    still_seconds: item.track ? null : seen.seconds,
    still_box: item.track ? null : seen.box,
  };
}

/** The frame second and box a reviewer picked as an item's evidence image (Set image); the track and text are not part of it. */
export interface ImagePick {
  seconds: number;
  box: Box;
}

/**
 * An evidence change proposed for an existing draft item (by the chat editor) and not yet trusted. It is held beside the item,
 * never in `reviewer` or `imagePick`, so nothing is cut from it until the reviewer confirms it (Confirm, or Adjust then Done).
 * A re-track carries the track the tracker made, with its `partial` and `lostAt` so the reviewer sees where it lost the item.
 */
export type EvidenceProposal =
  | { kind: 'retrack'; track: ReviewerTrack; reason: string | null }
  | { kind: 'set_image'; pick: ImagePick; reason: string | null };

/** The entry fields that name an item's image, frame and box: what a reviewer's own image keeps through a later re-track. */
export const IMAGE_ENTRY_KEYS = ['image', 'frame', 'bounding_box', 'timestamp_seconds', 'box_seconds', 'located'] as const;

/** The marker on an entry whose image a reviewer set (Set image): a later re-track keeps that image instead of the track's first frame. */
export const REVIEWER_IMAGE_SOURCE = 'reviewer';

/** The fields of an evidence entry that name its image: the crop and frame keys, the box, and the exact second they were cut at. */
export function imageEntryFields(seen: ImagePick, keys: { image: string; frame: string }): Record<string, unknown> {
  return {
    image: keys.image,
    frame: keys.frame,
    bounding_box: seen.box,
    timestamp_seconds: Math.round(seen.seconds),
    box_seconds: seen.seconds,
    located: true,
  };
}

/**
 * The fields a reviewer item adds to its evidence entry, apart from the image keys the server cuts. `pick` is the frame and
 * box the reviewer chose for the image: it replaces the track's first sample (or the still image) as where the image is cut.
 */
export function reviewerEntryFields(
  payload: ReviewerPayload,
  keys: { image: string; frame: string; track: string | null },
  pick: ImagePick | null = null,
): Record<string, unknown> {
  const first = payload.track?.samples[0];
  const seconds = first ? first.t : (payload.still_seconds ?? 0);
  const box = (first ? first.box : payload.still_box) as Box;
  return {
    source: 'reviewer',
    ...imageEntryFields(pick ?? { seconds, box }, keys),
    ...(payload.track && keys.track
      ? {
          track: keys.track,
          track_first_seen_seconds: payload.track.span[0],
          track_last_seen_seconds: payload.track.span[1],
          track_source: 'reviewer',
          track_partial: payload.track.partial,
        }
      : {}),
    ...(payload.ai_proposal ? { ai_proposal: payload.ai_proposal } : {}),
  };
}
