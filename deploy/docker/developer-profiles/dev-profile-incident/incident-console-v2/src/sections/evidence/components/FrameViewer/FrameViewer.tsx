// SPDX-License-Identifier: Apache-2.0
'use client';

import { useState } from 'react';
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
  return (
    <figure className={`m-0 ${className}`} data-testid="frame-viewer">
      <div className="relative aspect-video overflow-hidden rounded-xl bg-black">
        {!failed && (
          <img
            alt={`Video frame at ${formatClock(seconds)}`}
            className="block h-full w-full object-contain"
            onError={() => setFailedSrc(src)}
            src={src}
          />
        )}
        {failed && (
          <div className="grid h-full place-items-center p-4 text-center text-sm text-white/70" data-testid="frame-viewer-missing">
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
                className={`absolute border-2 border-dashed ${OUTLINE[item.kind]} ${selected ? 'border-solid shadow-[0_0_0_2px_#12211b] z-10' : ''}`}
                data-box-id={item.id}
                key={item.id}
                onClick={() => onSelect?.(item.id)}
                style={style}
                type="button"
              >
                <span
                  className={`absolute -top-5 left-[-2px] whitespace-nowrap rounded px-1.5 py-px text-[10.5px] font-semibold text-white ${KIND_COLOUR[item.kind]}`}
                >
                  {item.label}
                </span>
              </button>
            );
          })}
      </div>
      <figcaption className="mt-1 font-mono text-[11px] text-ink/50">{formatClock(seconds)}</figcaption>
    </figure>
  );
}
