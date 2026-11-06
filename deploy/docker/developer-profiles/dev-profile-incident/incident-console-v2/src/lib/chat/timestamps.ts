// SPDX-License-Identifier: Apache-2.0

// Finds the video times in a chat answer, so each one can be clicked. Browser-safe.
// An answer's text is never rewritten: joining the segments gives it back exactly.

export type ChatSegment = { kind: 'text'; text: string } | { kind: 'time'; text: string; seconds: number };

// h:mm:ss or m:ss (seconds always two digits), not part of a longer token, and not a time of day.
const TIME =
  /(?<![\w:./])(?:(\d{1,2}):([0-5]\d):([0-5]\d)|(\d{1,3}):([0-5]\d))(\.\d+)?(?!\w|:\d|\s*(?:[ap]\.?m\b|hrs?\b|hours?\b|o'?clock\b|utc\b|gmt\b|sgt\b))/gi;
// A date just before a time makes it a time of day: "2026-11-06 10:15", "6/11/2026, 10:15".
const DATE_BEFORE = /\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}[,\s]*$/;
// A hyphen glued to a word or number before a time: "abc-1:23". Only a range ("0:15-0:30") may do that.
const JOINED_BEFORE = /[\w]-$/;

function secondsOf(match: RegExpExecArray): number {
  const [, hours, minutes, seconds, shortMinutes, shortSeconds, fraction] = match;
  const whole =
    hours !== undefined ? Number(hours) * 3600 + Number(minutes) * 60 + Number(seconds) : Number(shortMinutes) * 60 + Number(shortSeconds);
  return whole + (fraction ? Number(fraction) : 0);
}

/**
 * Whether a time is a position in this video. As the report rules do (`0 <= T < duration + 1`), a time in the clip's
 * last, partly played second counts. With no known length every time counts, and the seek itself is bounded.
 */
function insideVideo(seconds: number, durationSeconds: number | null | undefined): boolean {
  return !(typeof durationSeconds === 'number' && Number.isFinite(durationSeconds) && durationSeconds > 0) || seconds < durationSeconds + 1;
}

/**
 * An answer as plain text and video times. Each end of a range is its own time. A time past the video's end stays plain
 * text as written: it is shown, but is not offered as a place to jump to. So does a time in `unsupported`, one the agent
 * found the report does not hold: it looks valid, but nothing backs it.
 */
export function segmentChatText(
  content: string,
  { durationSeconds, unsupported = [] }: { durationSeconds?: number | null; unsupported?: readonly string[] } = {},
): ChatSegment[] {
  const segments: ChatSegment[] = [];
  let textStart = 0;
  let lastTimeEnd = -1;
  for (const match of content.matchAll(TIME)) {
    const start = match.index;
    const before = content.slice(0, start);
    const inRange = start === lastTimeEnd + 1 && content[lastTimeEnd] === '-';
    if (DATE_BEFORE.test(before) || (JOINED_BEFORE.test(before) && !inRange)) continue;
    const seconds = secondsOf(match);
    if (!insideVideo(seconds, durationSeconds) || unsupported.includes(match[0])) continue;
    if (start > textStart) segments.push({ kind: 'text', text: content.slice(textStart, start) });
    segments.push({ kind: 'time', text: match[0], seconds });
    textStart = start + match[0].length;
    lastTimeEnd = textStart;
  }
  if (textStart < content.length) segments.push({ kind: 'text', text: content.slice(textStart) });
  return segments;
}

/** Where a seek lands: null for a value that is no position, else the second, held inside a known length. */
export function seekTarget(seconds: number, durationSeconds?: number | null): number | null {
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  const bounded = typeof durationSeconds === 'number' && Number.isFinite(durationSeconds) && durationSeconds > 0;
  return bounded ? Math.min(seconds, durationSeconds) : seconds;
}
