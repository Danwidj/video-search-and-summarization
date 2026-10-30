// SPDX-License-Identifier: Apache-2.0
'use client';

import { useEffect, useRef, useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { boxRegion, boxStyle, containFrame, cropImageStyle, cropRegion, evidenceFrameState } from '@/lib/evidence/frame-geometry';
import { formatClock } from '@/modules/reports/domain/normalize';
import type { EvidenceItemType } from '@/modules/reports/domain/revision';

export const KIND_COLOUR: Record<EvidenceItemType, string> = { entity: 'bg-moss', instrument: 'bg-clay', asset: 'bg-[#5f7896]' };
export const KIND_LABEL: Record<EvidenceItemType, string> = { entity: 'Entity', instrument: 'Instrument', asset: 'Asset' };

export interface EvidenceFrameProps {
  /** The stored evidence image (a signed crop or an uploaded image), when there is one. */
  src?: string | null;
  /** A signed full frame to crop when there is no stored image. */
  frameSrc?: string | null;
  /** [ymin, xmin, ymax, xmax] normalised to 0-1000 over the frame. */
  box?: readonly number[] | null;
  /** Width / height of frameSrc; 16 / 9 unless the video says otherwise. */
  frameAspect?: number;
  kind?: EvidenceItemType;
  label: string;
  /** Video second the evidence was taken from. */
  seconds?: number | null;
  /** The crop is still being produced. */
  pending?: boolean;
  selected?: boolean;
  /** Width / height of the tile. */
  aspect?: number;
  /** Cut the tile from frameSrc around the box and draw the box on it; the stored image stands in when the frame cannot load. */
  drawBox?: boolean;
  /** Show the whole frame, none of it cut, with the box drawn on it (no box when the object was not located). */
  fullFrame?: boolean;
  /** The detector did not find the object: the frame is shown as it is, with a note instead of a box. */
  notLocated?: boolean;
  className?: string;
}

/** One evidence tile: the whole frame with its box, else the stored image whole, else a crop of the frame, else a pending or missing placeholder. */
export function EvidenceFrame({
  src,
  frameSrc,
  box,
  frameAspect = 16 / 9,
  kind,
  label,
  seconds,
  pending,
  selected,
  aspect = 4 / 3,
  drawBox = false,
  fullFrame = false,
  notLocated = false,
  className = '',
}: EvidenceFrameProps) {
  const [failed, setFailed] = useState(false);
  const [frameFailed, setFrameFailed] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const [tileAspect, setTileAspect] = useState(aspect);
  // The frame's real shape, once it has loaded; a 4:3 clip cropped as 16:9 would be skewed.
  const [loadedAspect, setLoadedAspect] = useState<number | null>(null);
  // A drawn-box tile has a size its container sets, so crop to the aspect it actually has.
  useEffect(() => {
    const tile = ref.current;
    if (!(drawBox || fullFrame) || !tile) return;
    const measure = () => tile.clientWidth && tile.clientHeight && setTileAspect(tile.clientWidth / tile.clientHeight);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(tile);
    return () => observer.disconnect();
  }, [drawBox, fullFrame]);
  const framed = drawBox && !!frameSrc && !!boxRegion(box) && !frameFailed;
  const whole = fullFrame && !!frameSrc && !frameFailed;
  const state = whole
    ? 'full-frame'
    : framed
      ? 'frame-crop'
      : evidenceFrameState({ src, frameSrc: drawBox || fullFrame ? null : frameSrc, box, pending, failed });
  const fit = containFrame(loadedAspect ?? frameAspect, tileAspect);
  const region =
    state === 'frame-crop' ? cropRegion(box, framed && loadedAspect ? loadedAspect : frameAspect, framed ? tileAspect : aspect) : null;
  const boxed = framed && region ? boxRegion(box) : null;
  const onError = () => (framed || whole ? setFrameFailed(true) : setFailed(true));
  const pct = (n: number) => `${+(n * 100).toFixed(3)}%`;
  return (
    <div
      ref={ref}
      aria-label={label}
      className={`relative overflow-hidden rounded-xl bg-muted ${selected ? 'ring-2 ring-ring ring-offset-2 ring-offset-background' : ''} ${className}`}
      data-state={state}
      data-testid="evidence-frame"
      role="img"
      style={{ aspectRatio: String(aspect) }}
    >
      {state === 'image' && (
        // biome-ignore lint/performance/noImgElement: a presigned R2 URL that next/image would proxy and re-encode through the console server
        <img alt="" className="h-full w-full object-contain" onError={onError} src={src ?? undefined} />
      )}
      {state === 'frame-crop' && region && (
        // biome-ignore lint/performance/noImgElement: a presigned R2 URL that next/image would proxy and re-encode through the console server
        <img
          alt=""
          className="absolute max-w-none"
          onError={onError}
          onLoad={(event) => {
            const { naturalWidth, naturalHeight } = event.currentTarget;
            if (drawBox && naturalWidth && naturalHeight) setLoadedAspect(naturalWidth / naturalHeight);
          }}
          src={frameSrc ?? undefined}
          style={cropImageStyle(region)}
        />
      )}
      {state === 'full-frame' && (
        <div
          className="absolute"
          style={{
            left: pct((1 - fit.w) / 2),
            top: pct((1 - fit.h) / 2),
            width: pct(fit.w),
            height: pct(fit.h),
          }}
        >
          {/* biome-ignore lint/performance/noImgElement: a presigned R2 URL that next/image would proxy and re-encode through the console server */}
          <img
            alt=""
            className="h-full w-full"
            onError={onError}
            onLoad={(event) => {
              const { naturalWidth, naturalHeight } = event.currentTarget;
              if (naturalWidth && naturalHeight) setLoadedAspect(naturalWidth / naturalHeight);
            }}
            src={frameSrc ?? undefined}
          />
          {boxStyle(box) && (
            <span
              className="pointer-events-none absolute rounded-sm border-2 border-solid border-signal"
              data-testid="evidence-frame-box"
              style={boxStyle(box) ?? undefined}
            />
          )}
        </div>
      )}
      {boxed && region && (
        <span
          className="pointer-events-none absolute rounded-sm border-2 border-solid border-signal"
          data-testid="evidence-frame-box"
          style={{
            left: pct((boxed.x - region.x) / region.w),
            top: pct((boxed.y - region.y) / region.h),
            width: pct(boxed.w / region.w),
            height: pct(boxed.h / region.h),
          }}
        />
      )}
      {state === 'pending' && (
        <Skeleton className="grid h-full w-full place-items-center rounded-none text-[11px] text-muted-foreground">
          Cropping frame{seconds != null ? ` ${formatClock(seconds)}` : ''}…
        </Skeleton>
      )}
      {state === 'missing' && (
        <div className="grid h-full place-items-center border border-destructive/20 bg-destructive/10 p-2 text-center text-[11.5px] text-destructive">
          <span>
            <b>Image unavailable</b>
            <br />
            {failed ? 'The image failed to load.' : 'No stored image or frame for this item.'}
          </span>
        </div>
      )}
      {notLocated && state !== 'pending' && state !== 'missing' && (
        <Badge
          variant="outline"
          className="absolute bottom-1.5 left-1.5 border-transparent bg-black/60 px-1.5 py-0.5 text-[10.5px] text-white backdrop-blur-xs"
          data-testid="evidence-not-located"
        >
          Object not located
        </Badge>
      )}
      {kind && (
        <Badge
          variant="secondary"
          className="absolute top-1.5 left-1.5 gap-1 border-transparent bg-background/90 px-2 py-0.5 text-[10.5px] font-semibold text-foreground shadow-xs backdrop-blur-xs"
        >
          <i className={`inline-block h-2 w-2 rounded-full ${KIND_COLOUR[kind]}`} />
          {KIND_LABEL[kind]}
        </Badge>
      )}
      {seconds != null && (
        <Badge
          variant="outline"
          className="absolute right-1.5 bottom-1.5 border-transparent bg-black/60 px-1.5 py-0.5 font-mono text-[10.5px] text-white backdrop-blur-xs"
        >
          {formatClock(seconds)}
        </Badge>
      )}
    </div>
  );
}

export { EvidenceFrame as CropImage };
