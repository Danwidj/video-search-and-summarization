// SPDX-License-Identifier: Apache-2.0

// The caption pass of an agent-mode run (vss-agent INCIDENT_CHUNKING_ENABLED):
// the clip cut into overlapping windows, each captioned by the VLM. Stored as
// the agent returned it in the run notes (response.chunkTimeline) and read here
// leniently: an entry that is not a usable window is skipped, never repaired.

/** One captioned window, in seconds from the start of the whole video. */
export interface ChunkWindow {
  startSeconds: number;
  endSeconds: number;
  caption: string;
  /** The caption's own `[Xs-Ys]` stamps, already offset to whole-video seconds. */
  events: Array<{ startSeconds: number; endSeconds: number; text: string }>;
}

type Row = Record<string, unknown>;

const asRow = (value: unknown): Row | null => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : null);
const seconds = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null);

/** The usable windows of a stored chunk timeline, ordered by start; empty when there is none. */
export function chunkTimelineFrom(raw: unknown): ChunkWindow[] {
  if (!Array.isArray(raw)) return [];
  const windows: ChunkWindow[] = [];
  for (const entry of raw) {
    const row = asRow(entry);
    if (!row) continue;
    const start = seconds(row.start);
    const end = seconds(row.end);
    const caption = typeof row.caption === 'string' ? row.caption.trim() : '';
    if (start === null || end === null || end <= start || !caption) continue;
    const events = (Array.isArray(row.events) ? row.events : []).flatMap((value) => {
      const event = asRow(value);
      const eventStart = seconds(event?.start);
      const eventEnd = seconds(event?.end);
      const text = typeof event?.text === 'string' ? event.text.trim() : '';
      return eventStart === null || eventEnd === null || !text ? [] : [{ startSeconds: eventStart, endSeconds: eventEnd, text }];
    });
    windows.push({ startSeconds: start, endSeconds: end, caption, events });
  }
  return windows.sort((a, b) => a.startSeconds - b.startSeconds || a.endSeconds - b.endSeconds);
}

/**
 * The window playing at `time`: of the windows containing it (start and end
 * inclusive), the one with the latest start, so the 2 s overlap always hands
 * over to the next window. -1 before the first window, after the last and in a gap.
 * `windows` must be ordered by start (as chunkTimelineFrom returns them).
 */
export function activeChunkIndex(windows: ChunkWindow[], time: number): number {
  for (let index = windows.length - 1; index >= 0; index -= 1) {
    const window = windows[index];
    if (window.startSeconds <= time && time <= window.endSeconds) return index;
  }
  return -1;
}
