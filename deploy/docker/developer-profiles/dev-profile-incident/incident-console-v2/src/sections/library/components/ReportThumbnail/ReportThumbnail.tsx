// SPDX-License-Identifier: Apache-2.0
'use client';

import { useState } from 'react';
import type * as React from 'react';
import { VideoIcon } from 'lucide-react';
import { cn } from 'cn';

import type { ReportLibraryItem } from '@/modules/reports/domain/storage';
import { libraryCardThumbnail } from '@/lib/ui/thumbnail';
import { severityClass } from '@/sections/library/components/Shared';
import { Badge } from '@/components/ui/badge';

export function ReportThumbnail({
  thumbnailUrl,
  severity,
  kind,
  duration,
  alt,
  children,
}: {
  thumbnailUrl?: string;
  severity: number;
  kind?: ReportLibraryItem['kind'];
  duration?: string;
  alt: string;
  children?: React.ReactNode;
}) {
  const [failed, setFailed] = useState(false);
  const { image: view, severityLabel, kindLabel } = libraryCardThumbnail({ thumbnailUrl, severity, kind: kind || 'ai' }, failed);

  return (
    <figure
      aria-label="Video screenshot preview"
      className="relative h-32 shrink-0 overflow-hidden lg:h-auto lg:min-h-12 lg:flex-1 bg-[#dfe3dc]"
    >
      {view.kind === 'image' ? (
        // biome-ignore lint/performance/noImgElement: a presigned R2 URL that next/image would proxy and re-encode through the console server
        <img
          alt={alt}
          className="size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
          loading={view.loading}
          onError={() => setFailed(true)}
          src={view.src}
        />
      ) : (
        <div
          className="absolute inset-0 grid place-items-center bg-gradient-to-br from-[#e6e9e2] to-[#d3d8cf] text-ink/30"
          data-testid="library-thumbnail-skeleton"
        >
          <VideoIcon className="size-7" />
        </div>
      )}
      <Badge
        variant="outline"
        className={cn(
          'absolute left-2.5 top-2.5 h-auto rounded-full border px-2 py-0.5 text-[11px] font-bold leading-4',
          severityClass(severity),
        )}
      >
        {severityLabel}
      </Badge>
      <span className="sr-only" data-testid="library-kind-badge">
        {kindLabel}
      </span>
      {duration && (
        <span className="absolute bottom-2 left-2.5 rounded bg-ink/80 px-1.5 py-0.5 font-mono text-[11px] text-white">{duration}</span>
      )}
      {children}
    </figure>
  );
}
