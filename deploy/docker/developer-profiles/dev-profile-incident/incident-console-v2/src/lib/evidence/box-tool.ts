// SPDX-License-Identifier: Apache-2.0

// Pure rules for the box tool in Edit mode: reading the describe and track routes' answers, changing a track the way the
// preview buttons do (extend, gone from here on), and putting the finished item into the edit draft. The evidence image of
// an item is always the first second it is seen: the track's first sample, or the still image's second.

import { boxRegion } from '@/lib/evidence/frame-geometry';
import {
  BOX_ITEM_TYPES,
  type Box,
  type BoxItemType,
  type BoxProposal,
  type BoxToolItem,
  type ReviewerTrack,
  type ReviewerTrackSample,
} from '@/modules/reports/domain/box-item';
import { type EditDraft, newEntityDraft, newItemDetails } from '@/modules/reports/domain/edit-draft';

/** How far one "Extend" button reaches, and the window either side of a fresh box. */
export const TRACK_WINDOW_SECONDS = 3;

const isBox = (value: unknown): value is Box => Array.isArray(value) && value.length === 4 && !!boxRegion(value as number[]);
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);
const text = (value: unknown) => (typeof value === 'string' ? value.trim() : '');

/** The describe route's answer: a proposal, or null with the plain reason the model could not identify the box. */
export function parseDescribeResponse(body: unknown): { proposal: BoxProposal | null; reason: string | null } {
  const raw = (body ?? {}) as { proposal?: Record<string, unknown> | null; reason?: unknown };
  const reason = text(raw.reason) || null;
  const p = raw.proposal;
  if (!p || typeof p !== 'object') return { proposal: null, reason };
  const itemType = (BOX_ITEM_TYPES as readonly unknown[]).includes(p.itemType) ? (p.itemType as BoxItemType) : 'asset';
  const threat = finite(p.threatLevel) && p.threatLevel >= 1 && p.threatLevel <= 5 ? Math.round(p.threatLevel) : null;
  return {
    proposal: {
      itemType,
      name: text(p.name),
      description: text(p.description),
      holder: text(p.holder) || null,
      threatLevel: threat,
      confidence: finite(p.confidence) ? p.confidence : 0,
    },
    reason,
  };
}

/** The track route's answer. Null when it holds no usable sample (the tracker produced nothing). */
export function parseTrackResponse(body: unknown): ReviewerTrack | null {
  const raw = ((body ?? {}) as { track?: Record<string, unknown> | null }).track;
  if (!raw || typeof raw !== 'object' || !Array.isArray(raw.samples)) return null;
  const samples: ReviewerTrackSample[] = [];
  for (const sample of raw.samples as Array<Record<string, unknown>>) {
    if (!sample || !finite(sample.t) || sample.t < 0 || !isBox(sample.box)) continue;
    samples.push({ t: sample.t, box: [...sample.box] as Box, conf: finite(sample.conf) ? sample.conf : 0 });
  }
  if (!samples.length) return null;
  samples.sort((a, b) => a.t - b.t);
  return {
    source: 'reviewer',
    samples,
    span: [samples[0].t, samples[samples.length - 1].t],
    partial: raw.partial === true,
    lostAt: finite(raw.lostAt) ? raw.lostAt : null,
  };
}

const spanOf = (samples: readonly ReviewerTrackSample[]): [number, number] => [samples[0].t, samples[samples.length - 1].t];

/** The track after a further run over one side of it: the new samples win where the two overlap, and the latest run says whether it was lost. */
export function extendTrack(track: ReviewerTrack, run: ReviewerTrack, direction: 'back' | 'on'): ReviewerTrack {
  const [first, last] = track.span;
  const kept = track.samples.filter((sample) => (direction === 'back' ? sample.t >= first : sample.t <= last));
  const fresh = run.samples.filter((sample) => (direction === 'back' ? sample.t < first : sample.t > last));
  const samples = [...kept, ...fresh].sort((a, b) => a.t - b.t);
  return { source: 'reviewer', samples, span: spanOf(samples), partial: run.partial, lostAt: run.lostAt };
}

/** The track ended at a second ("Gone from here on"): later samples go, and it is no longer partial. Null when nothing would be left. */
export function endTrackAt(track: ReviewerTrack, seconds: number): ReviewerTrack | null {
  const samples = track.samples.filter((sample) => sample.t <= seconds);
  if (!samples.length) return null;
  return { source: 'reviewer', samples, span: spanOf(samples), partial: false, lostAt: null };
}

/** Where an item is first seen: the track's first sample, else the still image's second and box. Null before anything is boxed. */
export function firstSeen(item: Pick<BoxToolItem, 'track' | 'stillSeconds' | 'stillBox'>): { seconds: number; box: Box } | null {
  if (item.track) return { seconds: item.track.samples[0].t, box: item.track.samples[0].box };
  return item.stillSeconds !== undefined && item.stillBox ? { seconds: item.stillSeconds, box: item.stillBox } : null;
}

/** The body of a track run that extends an existing track one window to one side, seeded at its edge sample. */
export function extensionRequest(track: ReviewerTrack, direction: 'back' | 'on') {
  const edge = direction === 'back' ? track.samples[0] : track.samples[track.samples.length - 1];
  return {
    seconds: edge.t,
    box: edge.box,
    backSeconds: direction === 'back' ? TRACK_WINDOW_SECONDS : 0,
    forwardSeconds: direction === 'on' ? TRACK_WINDOW_SECONDS : 0,
  };
}

/** Holder names offered on the card: the draft's entities by name, never by E1-style ids. */
export function holderChoices(draft: EditDraft): Array<{ key: string; name: string }> {
  const names = draft.entities.map((entity) => entity.label || entity.type);
  return draft.entities.map((entity, index) => {
    const name = names[index];
    const same = names.filter((other) => other === name).length > 1;
    return { key: entity.key, name: same ? `${name} (${names.slice(0, index + 1).filter((other) => other === name).length})` : name };
  });
}

/** What the draft item keeps of the box tool's result: the evidence image second and box, and the seen span. */
function seenPatch(item: BoxToolItem) {
  const seen = firstSeen(item);
  if (!seen) return {};
  const second = Math.max(0, Math.round(seen.seconds));
  const last = item.track ? Math.max(second, Math.ceil(item.track.samples[item.track.samples.length - 1].t)) : second;
  return {
    timestampSeconds: second,
    imageTimestampSeconds: second,
    imageBox: [...seen.box],
    boxItem: item,
    seenSpan: { first: Math.min(second, Math.floor(item.track ? item.track.samples[0].t : second)), last },
  };
}

type Spanless<T> = Omit<T, 'seenSpan'>;
const withoutSpan = <T extends { seenSpan?: unknown }>(patch: T): Spanless<T> => {
  const { seenSpan: _span, ...rest } = patch;
  return rest;
};

/** A new draft item from the box tool, as an entity, instrument or asset by the reviewer's chosen type. */
export function addBoxItem(draft: EditDraft, item: BoxToolItem, holderKey: string | null): EditDraft {
  const patch = seenPatch(item);
  const common = { ...withoutSpan(patch), description: item.description };
  if (item.itemType === 'entity') {
    const span = patch.seenSpan;
    const entity = newEntityDraft(draft, {
      ...common,
      label: item.name,
      ...(span ? { firstSeenSeconds: span.first, lastSeenSeconds: span.last } : {}),
    });
    return { ...draft, entities: [...draft.entities, entity] };
  }
  const base = { ...newItemDetails(item.itemType, draft), ...common, name: item.name };
  if (item.itemType === 'instrument') {
    return { ...draft, instruments: [...draft.instruments, { ...base, holderKey, threat_level: item.threatLevel ?? null }] };
  }
  return { ...draft, assets: [...draft.assets, base] };
}

/** An existing draft item re-tracked from a new box: its text and holder stay, its evidence image and seen span follow the track. */
export function retrackDraftItem(draft: EditDraft, kind: BoxItemType, key: string, item: BoxToolItem): EditDraft {
  const patch = seenPatch(item);
  const { seenSpan, ...rest } = patch;
  const fields = rest;
  if (kind === 'entity') {
    return {
      ...draft,
      entities: draft.entities.map((entity) =>
        entity.key === key
          ? { ...entity, ...fields, ...(seenSpan ? { firstSeenSeconds: seenSpan.first, lastSeenSeconds: seenSpan.last } : {}) }
          : entity,
      ),
    };
  }
  if (kind === 'instrument') {
    return {
      ...draft,
      instruments: draft.instruments.map((instrument) => (instrument.key === key ? { ...instrument, ...fields } : instrument)),
    };
  }
  return { ...draft, assets: draft.assets.map((asset) => (asset.key === key ? { ...asset, ...fields } : asset)) };
}
