// SPDX-License-Identifier: Apache-2.0

export type ReportThumbnailView = { kind: 'image'; loading: 'lazy'; src: string } | { kind: 'skeleton' };

export function reportThumbnailView(thumbnailUrl?: string, failed = false): ReportThumbnailView {
  return thumbnailUrl && !failed ? { kind: 'image', loading: 'lazy', src: thumbnailUrl } : { kind: 'skeleton' };
}

/** What a /library card shows: MVP1's report-card thumbnail. */
export interface LibraryCardThumbnail {
  /** The upload-time screenshot, else MVP1's skeleton; never an evidence crop. */
  image: ReportThumbnailView;
  severityLabel: string;
  kindLabel: 'Human' | 'AI';
}

/**
 * The card image for one library item. Only its screenshot URL is read, so an
 * item with evidence images but no screenshot shows the skeleton; `failed`
 * (the screenshot failed to load) shows it too.
 */
export function libraryCardThumbnail(
  item: { thumbnailUrl?: string; severity: number; kind: string },
  failed = false,
): LibraryCardThumbnail {
  return {
    image: reportThumbnailView(item.thumbnailUrl, failed),
    severityLabel: `Severity ${item.severity}`,
    kindLabel: item.kind === 'human' ? 'Human' : 'AI',
  };
}

export function thumbnailCaptureTime(durationSeconds: number): number {
  return Number.isFinite(durationSeconds) && durationSeconds > 0 ? durationSeconds * 0.25 : 0;
}
