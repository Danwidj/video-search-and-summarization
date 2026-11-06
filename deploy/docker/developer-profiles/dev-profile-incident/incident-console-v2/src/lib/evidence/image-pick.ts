// SPDX-License-Identifier: Apache-2.0

// Pure rules for "Set image" in Edit mode: where the dialog opens for an item, which seconds the reviewer may pick, and how
// the finished pick goes into the draft. A pick changes an item's evidence image only; its track and text stay as they were.

import { boxRegion } from '@/lib/evidence/frame-geometry';
import { pickSeconds } from '@/lib/evidence/frame-picker';
import type { EditDraft } from '@/modules/reports/domain/edit-draft';
import type { ItemEvidence } from '@/modules/reports/domain/report-view';
import type { Box, ImagePick, ReviewerDraftItem } from '@/modules/reports/domain/reviewer-item';
import type { EvidenceItemType } from '@/modules/reports/domain/revision';

/** The frame route answers 422 for a second at or past the video's end, so a pick stops this far short of it. */
const END_MARGIN = 0.1;

/** The picked second to three decimals, the precision the frame route and the server's cut both read. */
export const roundPick = (seconds: number): number => Math.round(seconds * 1000) / 1000;

/** The last second a pick may name: just inside the video's end, or null while its length is unknown. */
export function pickCeiling(durationSeconds: number | null): number | null {
  return durationSeconds === null ? null : Math.max(0, roundPick(durationSeconds - END_MARGIN));
}

/** A picked second moved by `delta` (a step button or the slider): never negative, never past the ceiling. */
export function movePick(seconds: number, delta: number, durationSeconds: number | null): number {
  return roundPick(pickSeconds(seconds + delta, pickCeiling(durationSeconds)));
}

interface DraftItemForPick {
  imagePick: ImagePick | null;
  reviewer: ReviewerDraftItem | null;
  image: string | null;
  timestampSeconds: number | null;
}

export interface PickSeed {
  seconds: number;
  /** The box the item's evidence image has now, drawn on the frame to start from; null when it has none (the detector failed). */
  box: Box | null;
}

const asBox = (box: readonly number[] | null | undefined): Box | null => (box && boxRegion(box) ? (box as unknown as Box) : null);

/**
 * Where the dialog opens: the reviewer's own pick, else the draft's track or still, else the saved item's frame and box while
 * the draft still has the saved image, else the item's most-visible second with no box. An item with no box opens unboxed.
 */
export function pickSeed(
  item: DraftItemForPick,
  saved: Pick<ItemEvidence, 'image' | 'located' | 'boxSeconds' | 'boundingBox'> | null,
): PickSeed {
  if (item.imagePick) return item.imagePick;
  const first = item.reviewer?.track?.samples[0];
  if (first) return { seconds: first.t, box: asBox(first.box) };
  const still = item.reviewer?.stillBox ? asBox(item.reviewer.stillBox) : null;
  if (still && item.reviewer?.stillSeconds !== undefined) return { seconds: item.reviewer.stillSeconds, box: still };
  const fallback = item.timestampSeconds ?? 0;
  if (!saved || saved.image !== item.image) return { seconds: fallback, box: null };
  const box = saved.located === false ? null : asBox(saved.boundingBox);
  return { seconds: saved.boxSeconds ?? fallback, box };
}

const patchItem = <T extends { key: string; imagePick: ImagePick | null }>(items: T[], key: string, pick: ImagePick): T[] =>
  items.map((item) => (item.key === key ? { ...item, imagePick: pick } : item));

/** The draft with an item's evidence image set to a frame and box the reviewer drew; nothing else about the item changes. */
export function setImagePick(draft: EditDraft, kind: EvidenceItemType, key: string, pick: ImagePick): EditDraft {
  if (kind === 'entity') return { ...draft, entities: patchItem(draft.entities, key, pick) };
  if (kind === 'instrument') return { ...draft, instruments: patchItem(draft.instruments, key, pick) };
  return { ...draft, assets: patchItem(draft.assets, key, pick) };
}
