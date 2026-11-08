// SPDX-License-Identifier: Apache-2.0

export type ReportThumbnailView = { kind: 'image'; loading: 'lazy'; src: string } | { kind: 'skeleton' };

export function reportThumbnailView(thumbnailUrl?: string, failed = false): ReportThumbnailView {
  return thumbnailUrl && !failed ? { kind: 'image', loading: 'lazy', src: thumbnailUrl } : { kind: 'skeleton' };
}

/** A video length as m:ss, or h:mm:ss from an hour; null when unknown or under a second. Whole seconds, rounded down. */
export function formatVideoDuration(seconds: unknown): string | null {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return null;
  const total = Math.floor(seconds);
  if (total < 1) return null;
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, '0');
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${minutes}:${secs}`;
}

/** What a /library card shows: MVP1's report-card thumbnail. */
export interface LibraryCardThumbnail {
  /** The upload-time screenshot, else MVP1's skeleton; never an evidence crop. */
  image: ReportThumbnailView;
  severityLabel: string;
  kindLabel: 'Human' | 'AI';
  /** The video's length badge (m:ss or h:mm:ss); null when the length is unknown. */
  durationLabel: string | null;
}

/**
 * The card image for one library item. Only its screenshot URL is read, so an
 * item with evidence images but no screenshot shows the skeleton; `failed`
 * (the screenshot failed to load) shows it too.
 */
export function libraryCardThumbnail(
  item: { thumbnailUrl?: string; severity: number; kind: string; durationSeconds?: number | null },
  failed = false,
): LibraryCardThumbnail {
  return {
    image: reportThumbnailView(item.thumbnailUrl, failed),
    severityLabel: `Severity ${item.severity}`,
    kindLabel: item.kind === 'human' ? 'Human' : 'AI',
    durationLabel: formatVideoDuration(item.durationSeconds),
  };
}

export function thumbnailCaptureTime(durationSeconds: number): number {
  return Number.isFinite(durationSeconds) && durationSeconds > 0 ? durationSeconds * 0.25 : 0;
}
