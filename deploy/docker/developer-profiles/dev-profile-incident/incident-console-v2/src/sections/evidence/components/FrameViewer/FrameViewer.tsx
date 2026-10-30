// SPDX-License-Identifier: Apache-2.0
'use client';

import { useState } from 'react';
import { Badge } from '@/components/ui/badge';
import { KIND_COLOUR } from '@/sections/evidence/components/EvidenceFrame';
import { boxStyle } from '@/lib/evidence/frame-geometry';
import { formatClock } from '@/modules/reports/domain/normalize';
import type { EvidenceItemType } from '@/modules/reports/domain/revision';

export interface FrameBox {
  id: string;
  label: string;
  kind: EvidenceItemType;
  /** [ymin, xmin, ymax, xmax] normalised to 0-1000 over the frame. */
  box: readonly number[] | null;
}

const OUTLINE: Record<EvidenceItemType, string> = { entity: 'border-moss', instrument: 'border-clay', asset: 'border-[#5f7896]' };

export interface FrameViewerProps {
  /** The signed frame at `seconds`. */
  src?: string | null;
  seconds: number;
  boxes: FrameBox[];
  selectedId?: string | null;
  onSelect?: (id: string) => void;
  className?: string;
}

/** A video frame at a timestamp with the evidence boxes found in it; boxes without a usable geometry are left out. */
export function FrameViewer({ src, seconds, boxes, selectedId, onSelect, className = '' }: FrameViewerProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const failed = !src || failedSrc === src;
  // Fit the stage to the frame the video really has, so a 4:3 clip is not letterboxed in a 16:9 box.
  const [loaded, setLoaded] = useState<{ src: string; aspect: number } | null>(null);
  const aspect = loaded && loaded.src === src ? loaded.aspect : 16 / 9;
  return (
    <figure className={`m-0 ${className}`} data-testid="frame-viewer">
      <div className="relative overflow-hidden rounded-xl border border-border bg-black" style={{ aspectRatio: String(aspect) }}>
        {!failed && (
          // biome-ignore lint/performance/noImgElement: a presigned R2 URL that next/image would proxy and re-encode through the console server
          <img
            alt={`Video frame at ${formatClock(seconds)}`}
            className="block h-full w-full object-contain"
            onError={() => setFailedSrc(src)}
            onLoad={(event) => {
              const { naturalWidth, naturalHeight } = event.currentTarget;
              if (naturalWidth && naturalHeight) setLoaded({ src, aspect: naturalWidth / naturalHeight });
            }}
            src={src}
          />
        )}
        {failed && (
          <div className="grid h-full place-items-center p-4 text-center text-sm text-muted-foreground" data-testid="frame-viewer-missing">
            <span>
              <b>Frame unavailable</b>
              <br />
              The frame at {formatClock(seconds)} could not be loaded.
            </span>
          </div>
        )}
        {!failed &&
          boxes.map((item) => {
            const style = boxStyle(item.box);
            if (!style) return null;
            const selected = item.id === selectedId;
            return (
              <button
                aria-label={`${item.label} at ${formatClock(seconds)}`}
                aria-pressed={selected}
                className={`group absolute border-2 border-dashed transition-all focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring ${OUTLINE[item.kind]} ${selected ? 'border-solid ring-2 ring-ring z-10' : ''}`}
                data-box-id={item.id}
                key={item.id}
                onClick={() => onSelect?.(item.id)}
                style={style}
                type="button"
              >
                <Badge
                  className={`absolute top-0 left-0 h-auto max-w-full truncate rounded-none rounded-br-sm border-transparent px-1.5 py-px text-xs font-semibold text-white shadow-xs ${KIND_COLOUR[item.kind]} ${selected ? '' : 'invisible group-hover:visible group-focus-visible:visible'}`}
                >
                  {item.label}
                </Badge>
              </button>
            );
          })}
      </div>
      <figcaption className="mt-1 font-mono text-[11px] text-muted-foreground">{formatClock(seconds)}</figcaption>
    </figure>
  );
}
