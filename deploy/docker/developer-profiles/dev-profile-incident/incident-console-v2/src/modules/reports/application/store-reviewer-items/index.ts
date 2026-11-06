// SPDX-License-Identifier: Apache-2.0

// Store reviewer items: for each item of a saved edit that came from the box tool (or was re-tracked), cut the crop and the
// whole frame at the first-seen second, store them and the track file under `edit-<N>/`, and answer the evidence entry the
// new revision holds for it. An item whose image the reviewer set (Set image, `image_pick`) is cut at the frame and box they
// drew instead, and keeps its track and text; the entry then carries `image_source: 'reviewer'`, so a re-track in a later Save keeps
// that image. Without it an item with a track takes the first frame of the new track. The reviewer's own box is the box, so
// nothing is detected here. A box under 96 px on its short side is cut with a wider margin and enlarged (cropPlan).

import { boxRegion, cropPlan } from '@/lib/evidence/frame-geometry';
import { jpegSize } from '@/lib/evidence/jpeg-size';
import type { StructuredEdit } from '@/modules/reports/domain/edit-draft';
import {
  IMAGE_ENTRY_KEYS,
  type ImagePick,
  imageEntryFields,
  REVIEWER_IMAGE_SOURCE,
  reviewerEntryFields,
  type ReviewerPayload,
} from '@/modules/reports/domain/reviewer-item';
import {
  type EvidenceEntry,
  type EvidenceItemType,
  reviewerFrameKey,
  reviewerTrackKey,
  uploadedEvidenceKey,
} from '@/modules/reports/domain/revision';
import { StoreRejection } from '@/modules/shared/domain/common';
import type { ReviewerEvidenceStore } from '@/modules/reports/application/types';

// What a reviewer's new image, frame and track replace. The agent's `detected_box` and zoomed second look (`zoom_*`, and the
// `name_before`/`description_before` it left when it corrected a name) describe the old crop, so they go with it.
const REPLACED_FIELDS = [
  'image_gap',
  'track_gap',
  'detected_box',
  'zoom_checked',
  'zoom_confidence',
  'zoom_seen',
  'zoom_gap',
  'name_before',
  'description_before',
  'missing',
  'track',
  'track_first_seen_seconds',
  'track_last_seen_seconds',
  'track_source',
  'track_partial',
];

// A reviewer's new image replaces the old crop but not the item's track: only the box tool or a re-track replaces that.
const TRACK_FIELDS = ['track_gap', 'track', 'track_first_seen_seconds', 'track_last_seen_seconds', 'track_source', 'track_partial'];
const IMAGE_REPLACED_FIELDS = REPLACED_FIELDS.filter((field) => !TRACK_FIELDS.includes(field));

interface ReviewerItem {
  type: EvidenceItemType;
  itemId: string;
  sourceId: string | null;
  /** Null for an item that only had its image set. */
  reviewer: ReviewerPayload | null;
  pick: ImagePick | null;
}

/** The edit's items that carry reviewer data or a picked image, by their final IDs. */
export function reviewerItems(edit: StructuredEdit): ReviewerItem[] {
  const pick = <T extends { source_id: string | null; reviewer?: ReviewerPayload | null; image_pick?: ImagePick | null }>(
    type: EvidenceItemType,
    items: T[],
    idOf: (item: T) => string,
  ): ReviewerItem[] =>
    items.flatMap((item) =>
      item.reviewer || item.image_pick
        ? [{ type, itemId: idOf(item), sourceId: item.source_id, reviewer: item.reviewer ?? null, pick: item.image_pick ?? null }]
        : [],
    );
  return [
    ...pick('entity', edit.entities, (item) => item.entity_id),
    ...pick('instrument', edit.instruments, (item) => item.instrument_id),
    ...pick('asset', edit.assets, (item) => item.asset_id),
  ];
}

/** The first `edit-<n>` none of whose keys exist yet, so no object is ever overwritten. */
async function freeEditNumber(store: ReviewerEvidenceStore, keysAt: (n: number) => string[]): Promise<number> {
  for (let n = 1; ; n += 1) {
    const taken = await Promise.all(keysAt(n).map((key) => store.exists(key)));
    if (!taken.some(Boolean)) return n;
  }
}

/**
 * Stores every reviewer item of the edit and answers its evidence entry, keyed `<type>:<itemId>`. `parentEvidence` lets a
 * re-tracked item keep what its source entry says apart from the image, frame and track.
 */
export async function storeReviewerItems(
  store: ReviewerEvidenceStore,
  videoKey: string,
  edit: StructuredEdit,
  parentEvidence: EvidenceEntry[],
): Promise<Map<string, EvidenceEntry>> {
  const items = reviewerItems(edit);
  const entries = new Map<string, EvidenceEntry>();
  if (!items.length) return entries;
  const editNumber = await freeEditNumber(store, (n) =>
    items.flatMap((item) => [
      uploadedEvidenceKey(videoKey, n, item.itemId),
      reviewerFrameKey(videoKey, n, item.itemId),
      reviewerTrackKey(videoKey, n, item.itemId),
    ]),
  );
  for (const { type, itemId, sourceId, reviewer, pick } of items) {
    const first = reviewer?.track?.samples[0];
    const seconds = pick ? pick.seconds : first ? first.t : reviewer?.still_seconds;
    const box = pick ? pick.box : first ? first.box : reviewer?.still_box;
    const region = boxRegion(box);
    if (seconds === null || seconds === undefined || !region)
      throw new StoreRejection('invalid', `${itemId}: a reviewer item needs a track, or a still second and box`);
    const base = sourceId ? parentEvidence.find((entry) => entry.item_type === type && entry.item_id === sourceId) : undefined;
    // A reviewer's image from an earlier Save outlives a re-track: the new track replaces only the track fields.
    const keepsImage = !!reviewer && !pick && base?.image_source === REVIEWER_IMAGE_SOURCE;
    const keys = {
      image: uploadedEvidenceKey(videoKey, editNumber, itemId),
      frame: reviewerFrameKey(videoKey, editNumber, itemId),
      track: reviewer?.track ? reviewerTrackKey(videoKey, editNumber, itemId) : null,
    };
    if (!keepsImage) {
      // ffmpeg-static is memory-heavy. Running the crop and full-frame decode together can make the host kill one process
      // (Node then reports a null exit code), so keep the two short extractions sequential.
      const frame = await store.frame(videoKey, seconds, null);
      const size = jpegSize(frame);
      const plan = size ? cropPlan(region, size.width, size.height) : { region, scaleTo: null };
      const crop = await store.frame(videoKey, seconds, plan.region, plan.scaleTo);
      await store.put(keys.image, crop, 'image/jpeg');
      await store.put(keys.frame, frame, 'image/jpeg');
    }
    if (reviewer?.track && keys.track) await store.put(keys.track, Buffer.from(JSON.stringify(reviewer.track)), 'application/json');
    const replaced = reviewer ? REPLACED_FIELDS : IMAGE_REPLACED_FIELDS;
    const kept = Object.fromEntries(Object.entries(base ?? {}).filter(([key]) => !replaced.includes(key)));
    const fields = reviewer ? reviewerEntryFields(reviewer, keys, pick) : imageEntryFields({ seconds, box: box as ImagePick['box'] }, keys);
    if (keepsImage) for (const key of IMAGE_ENTRY_KEYS) delete fields[key];
    const entry = { ...kept, item_type: type, item_id: itemId, ...fields } as EvidenceEntry;
    if (pick) entry.image_source = REVIEWER_IMAGE_SOURCE;
    // A re-tracked or re-imaged item keeps the source its entry had (an AI entry has none); only a box the reviewer drew is `reviewer`.
    if (base) {
      if (base.source === undefined) delete entry.source;
      else entry.source = base.source;
    }
    entries.set(`${type}:${itemId}`, entry);
  }
  return entries;
}
