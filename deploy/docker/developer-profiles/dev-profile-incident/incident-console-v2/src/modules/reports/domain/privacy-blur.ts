// SPDX-License-Identifier: Apache-2.0

// Privacy blur (videos.blur_faces): the agent pixelates the heads of the people in every stored frame and crop of a run
// analysed with blur_faces; the console blurs the same heads in an evidence clip as it cuts it. Pure functions, no I/O,
// browser-safe: the head region of a person box (the same maths as the agent's utils/privacy_blur.py), whether a run was
// blurred, and the timed regions a clip blurs.

import type { TrackSample } from '@/modules/reports/domain/track';

/** [ymin, xmin, ymax, xmax] normalised to 0-1000, like every evidence box. */
export type NormalisedBox = [number, number, number, number];

/** The head is the top 30 % of a person box, raised and widened by 10 % of the box (the agent's HEAD_FRACTION and HEAD_PADDING). */
export const HEAD_FRACTION = 0.3;
export const HEAD_PADDING = 0.1;
/** A head recorded at one second is grown by this much of its own size on every side when it stands for a whole clip, since people move. */
export const STATIC_HEAD_PADDING = 0.25;
/** At most this many regions go into one clip's filter graph; a busier clip keeps the first ones (the item's own track first). */
export const MAX_CLIP_REGIONS = 32;
/** The smallest region side kept for a clip, on 0-1000 (1 % of the frame). */
export const MIN_REGION = 10;

const clamp = (value: number) => Math.max(0, Math.min(1000, Math.round(value)));
const isBox = (value: unknown): value is NormalisedBox =>
  Array.isArray(value) &&
  value.length === 4 &&
  value.every((n) => typeof n === 'number' && Number.isFinite(n)) &&
  value[0] < value[2] &&
  value[1] < value[3];

/** The head region of a person box: its top HEAD_FRACTION, raised and widened by HEAD_PADDING of the box, clamped to the frame. */
export function headRegion(box: readonly number[]): NormalisedBox {
  const [ymin, xmin, ymax, xmax] = box;
  const height = ymax - ymin;
  const width = xmax - xmin;
  return [
    clamp(ymin - HEAD_PADDING * height),
    clamp(xmin - HEAD_PADDING * width),
    clamp(ymin + HEAD_FRACTION * height),
    clamp(xmax + HEAD_PADDING * width),
  ];
}

/** `box` grown by `fraction` of its own height and width on every side, clamped to the frame. */
export function padBox(box: readonly number[], fraction: number): NormalisedBox {
  const [ymin, xmin, ymax, xmax] = box;
  const dy = (ymax - ymin) * fraction;
  const dx = (xmax - xmin) * fraction;
  return [clamp(ymin - dy), clamp(xmin - dx), clamp(ymax + dy), clamp(xmax + dx)];
}

/** The smallest box holding every box given. */
function union(boxes: readonly NormalisedBox[]): NormalisedBox {
  return [
    Math.min(...boxes.map((b) => b[0])),
    Math.min(...boxes.map((b) => b[1])),
    Math.max(...boxes.map((b) => b[2])),
    Math.max(...boxes.map((b) => b[3])),
  ];
}

/** Whether a run's notes say the agent blurred its stored images (response.privacy.blur_faces true). */
export function runBlurredFaces(response: { privacy?: unknown } | null | undefined): boolean {
  const privacy = response?.privacy;
  return Boolean(privacy && typeof privacy === 'object' && (privacy as { blur_faces?: unknown }).blur_faces === true);
}

/** The head boxes the agent blurred in an item's frame (its evidence entry's blur_regions); null when the entry records none. */
export function recordedBlurRegions(value: unknown): NormalisedBox[] | null {
  if (!Array.isArray(value)) return null;
  return value.filter(isBox).map((box) => [...box] as NormalisedBox);
}

/** One region a clip blurs: a box, from `fromSeconds` to `toSeconds` of the clip (null: the whole clip). */
export interface ClipBlurRegion {
  box: NormalisedBox;
  fromSeconds: number | null;
  toSeconds: number | null;
}

export interface ClipBlurInput {
  /** The clip's start and length in video seconds. */
  window: { startSeconds: number; lengthSeconds: number };
  /** The item's own track samples, when it has a track. */
  track: readonly TrackSample[] | null;
  /** The heads the agent blurred in the item's frame (blur_regions), when recorded. */
  recorded: readonly NormalisedBox[] | null;
  /** A person item's located box, used for its head when nothing else is known. */
  personBox: readonly number[] | null;
}

const round3 = (value: number) => Math.round(value * 1000) / 1000;

/**
 * The regions an evidence clip blurs, in clip seconds; null when nothing is known about the heads it shows (then no
 * blurred clip can be cut). Per second of the clip, the union of the head regions of the item's own track samples in
 * that second; for the whole clip, each head the agent blurred in the item's frame (padded, since people move), else a
 * person item's own head region (padded). An empty list means the agent recorded no head at the item's second.
 */
export function clipBlurRegions(input: ClipBlurInput): ClipBlurRegion[] | null {
  const { startSeconds, lengthSeconds } = input.window;
  const end = startSeconds + lengthSeconds;
  const regions: ClipBlurRegion[] = [];
  const buckets = new Map<number, NormalisedBox[]>();
  for (const sample of input.track ?? []) {
    if (sample.t < startSeconds - 0.5 || sample.t > end + 0.5 || !isBox(sample.box)) continue;
    const second = Math.floor(Math.max(0, sample.t - startSeconds));
    buckets.set(second, [...(buckets.get(second) ?? []), headRegion(sample.box)]);
  }
  for (const second of [...buckets.keys()].sort((a, b) => a - b)) {
    const heads = buckets.get(second) ?? [];
    regions.push({ box: union(heads), fromSeconds: second, toSeconds: round3(Math.min(lengthSeconds, second + 1)) });
  }
  if (input.recorded) {
    for (const box of input.recorded) regions.push({ box: padBox(box, STATIC_HEAD_PADDING), fromSeconds: null, toSeconds: null });
  } else if (input.personBox && isBox([...input.personBox])) {
    regions.push({ box: padBox(headRegion(input.personBox), STATIC_HEAD_PADDING), fromSeconds: null, toSeconds: null });
  }
  if (!regions.length && !input.recorded) return null;
  // A sliver of a box rounds to a zero-pixel crop, which ffmpeg reads as the whole frame: such regions are dropped.
  return regions.filter(({ box }) => box[2] - box[0] >= MIN_REGION && box[3] - box[1] >= MIN_REGION).slice(0, MAX_CLIP_REGIONS);
}

const fraction = (value: number) => (value / 1000).toFixed(4);

/**
 * The ffmpeg filter graph that scales the clip (`scale`, the plain clip's -vf) and box-blurs each region over its time
 * span: per region the frame is split, the region cropped and blurred, and laid back over itself with
 * enable='between(t,a,b)' (no enable for a whole-clip region). Positions are fractions of the scaled frame, rounded to
 * even pixels for yuv420p. The output pad is [blurred].
 */
export function clipBlurFilter(scale: string, regions: readonly ClipBlurRegion[]): string {
  const parts = [`[0:v:0]${scale}[v0]`];
  regions.forEach((region, i) => {
    const [ymin, xmin, ymax, xmax] = region.box;
    const x = (width: string) => `'2*trunc(${width}*${fraction(xmin)}/2)'`;
    const y = (height: string) => `'2*trunc(${height}*${fraction(ymin)}/2)'`;
    const w = `'2*trunc(iw*${fraction(xmax - xmin)}/2)'`;
    const h = `'2*trunc(ih*${fraction(ymax - ymin)}/2)'`;
    const enable = region.fromSeconds === null ? '' : `:enable='between(t,${region.fromSeconds},${region.toSeconds})'`;
    parts.push(
      `[v${i}]split[m${i}][c${i}]`,
      `[c${i}]crop=w=${w}:h=${h}:x=${x('iw')}:y=${y('ih')},boxblur=luma_radius='max(0,min(w,h)/2-1)':luma_power=3:chroma_radius='max(0,min(cw,ch)/2-1)':chroma_power=3[k${i}]`,
      `[m${i}][k${i}]overlay=x=${x('main_w')}:y=${y('main_h')}${enable}[v${i + 1}]`,
    );
  });
  parts.push(`[v${regions.length}]null[blurred]`);
  return parts.join(';');
}

/** What the face-blur toggle shows while its re-analysis job waits or runs. */
export function privacyJobLabel(job: { status: string }): string {
  return job.status === 'queued' ? 'Re-analysis queued…' : job.status === 'running' ? 'Re-analysing…' : 'Finishing…';
}
