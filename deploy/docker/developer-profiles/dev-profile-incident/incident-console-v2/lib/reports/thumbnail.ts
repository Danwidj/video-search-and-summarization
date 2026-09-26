// SPDX-License-Identifier: Apache-2.0

export type ReportThumbnailView =
  | { kind: 'image'; loading: 'lazy'; src: string }
  | { kind: 'skeleton' };

export function reportThumbnailView(thumbnailUrl?: string, failed = false): ReportThumbnailView {
  return thumbnailUrl && !failed
    ? { kind: 'image', loading: 'lazy', src: thumbnailUrl }
    : { kind: 'skeleton' };
}
