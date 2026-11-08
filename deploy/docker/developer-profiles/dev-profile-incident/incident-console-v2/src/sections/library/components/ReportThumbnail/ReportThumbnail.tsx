// SPDX-License-Identifier: Apache-2.0
'use client';

import { useEffect, useRef, useState } from 'react';
import type * as React from 'react';
import { VideoIcon } from 'lucide-react';
import { cn } from 'cn';
import { CARD_ZOOM } from '@/lib/ui/card-hover';
import { useHoverPreview } from '@/lib/ui/use-hover-preview';

import type { ReportLibraryItem } from '@/modules/reports/domain/storage';
import { libraryCardThumbnail } from '@/lib/ui/thumbnail';
import { severityClass } from '@/sections/library/components/Shared';
import { MutedVideo } from '@/components/muted-video';
import { Badge } from '@/components/ui/badge';

export function ReportThumbnail({
  thumbnailUrl,
  severity,
  kind,
  durationSeconds,
  alt,
  previewVideoId,
  children,
}: {
  thumbnailUrl?: string;
  severity: number;
  kind?: ReportLibraryItem['kind'];
  durationSeconds?: number | null;
  alt: string;
  /** Plays this video, muted, over the screenshot while the card is hovered. */
  previewVideoId?: string;
  children?: React.ReactNode;
}) {
  const [failed, setFailed] = useState(false);
  const figure = useRef<HTMLElement>(null);
  const previewUrl = useHoverPreview(figure, previewVideoId);
  const [ready, setReady] = useState(false);
  const clip = useRef<HTMLVideoElement>(null);

  // Leaving the card unmounts the clip: pause it and drop its source so the download stops, then show the screenshot again.
  useEffect(() => {
    const video = clip.current;
    if (!previewUrl || !video) return;
    return () => {
      video.pause();
      video.removeAttribute('src');
      video.load();
      setReady(false);
    };
  }, [previewUrl]);
  const {
    image: view,
    severityLabel,
    kindLabel,
    durationLabel,
  } = libraryCardThumbnail({ thumbnailUrl, severity, kind: kind || 'ai', durationSeconds }, failed);

  return (
    <figure
      ref={figure}
      aria-label="Video screenshot preview"
      className="relative h-32 shrink-0 overflow-hidden lg:h-auto lg:min-h-12 lg:flex-1 bg-[#dfe3dc]"
    >
      {view.kind === 'image' ? (
        // biome-ignore lint/performance/noImgElement: a presigned R2 URL that next/image would proxy and re-encode through the console server
        <img
          alt={alt}
          className={cn('size-full object-cover', CARD_ZOOM)}
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
      {previewUrl && (
        <MutedVideo
          autoPlay
          className={cn('absolute inset-0 size-full object-cover', CARD_ZOOM, ready ? 'opacity-100' : 'opacity-0')}
          loop
          onCanPlay={() => setReady(true)}
          onEmptied={() => setReady(false)}
          onError={() => setReady(false)}
          playsInline
          ref={clip}
          src={previewUrl}
          tabIndex={-1}
        />
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
      {durationLabel && (
        <span
          className="absolute bottom-2 right-2.5 rounded bg-ink/80 px-1.5 py-0.5 font-mono text-[11px] text-white tabular-nums"
          data-testid="library-duration-badge"
        >
          {durationLabel}
        </span>
      )}
      {children}
    </figure>
  );
}
