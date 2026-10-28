// SPDX-License-Identifier: Apache-2.0
'use client';

// The library card's image, restored from MVP1's report card (before #185):
// the video's upload-time screenshot only, MVP1's skeleton when there is none
// or it fails to load, and MVP1's severity and AI/Human badges on top. The
// screenshot is never replaced by an evidence crop.

import { useState } from 'react';

import type { ReportLibraryItem } from '@/modules/reports/domain/storage';
import { libraryCardThumbnail } from '@/lib/ui/thumbnail';
import { severityClass } from '@/sections/library/components/Shared';

export function ReportThumbnail({
  thumbnailUrl,
  severity,
  kind,
}: {
  thumbnailUrl?: string;
  severity: number;
  kind: ReportLibraryItem['kind'];
}) {
  // One failed load shows the skeleton for good: the image is not requested again.
  const [failed, setFailed] = useState(false);
  const { image: view, severityLabel, kindLabel } = libraryCardThumbnail({ thumbnailUrl, severity, kind }, failed);
  return (
    // A figure (not a div) so the label belongs to a role that supports it; Tailwind's base styles zero its margins.
    <figure aria-label="Video screenshot preview" className="relative aspect-video overflow-hidden bg-[#dfe3dc]">
      {view.kind === 'image' ? (
        // biome-ignore lint/performance/noImgElement: a presigned R2 URL that next/image would proxy and re-encode through the console server; MVP1 used a plain lazy img
        <img alt="" className="h-full w-full object-cover" loading={view.loading} onError={() => setFailed(true)} src={view.src} />
      ) : (
        <div data-testid="library-thumbnail-skeleton">
          <div className="absolute inset-0 bg-linear-to-br from-white/35 to-transparent" />
          <div className="absolute inset-x-8 bottom-8 space-y-3">
            <div className="h-3 w-2/3 rounded-full bg-ink/15" />
            <div className="h-3 w-full rounded-full bg-ink/10" />
            <div className="h-3 w-4/5 rounded-full bg-ink/10" />
          </div>
          <div className="absolute left-1/2 top-1/2 h-14 w-20 -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white/55 shadow-xs">
            <div className="absolute left-1/2 top-1/2 h-0 w-0 -translate-x-1/3 -translate-y-1/2 border-y-10 border-l-16 border-y-transparent border-l-ink/25" />
          </div>
        </div>
      )}
      <span className={`absolute left-3 top-3 rounded-full px-3 py-1.5 text-xs font-bold ${severityClass(severity)}`}>{severityLabel}</span>
      <span
        className="absolute right-3 top-3 rounded-full bg-white/90 px-3 py-1.5 text-xs font-semibold text-ink"
        data-testid="library-kind-badge"
      >
        {kindLabel}
      </span>
    </figure>
  );
}
