// SPDX-License-Identifier: Apache-2.0
'use client';

import { useState } from 'react';
import { cropImageStyle, cropRegion, evidenceFrameState } from '@/lib/evidence/frame-geometry';
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
  className?: string;
}

/** One evidence tile: the stored image, else a crop of the frame, else a pending or missing placeholder. */
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
  className = '',
}: EvidenceFrameProps) {
  const [failed, setFailed] = useState(false);
  const state = evidenceFrameState({ src, frameSrc, box, pending, failed });
  const region = state === 'frame-crop' ? cropRegion(box, frameAspect, aspect) : null;
  const onError = () => setFailed(true);
  return (
    <div
      aria-label={label}
      className={`relative overflow-hidden rounded-2xl bg-[#2a312e] ${selected ? 'ring-2 ring-ink' : ''} ${className}`}
      data-state={state}
      data-testid="evidence-frame"
      role="img"
      style={{ aspectRatio: String(aspect) }}
    >
      {state === 'image' && (
        // biome-ignore lint/performance/noImgElement: a presigned R2 URL that next/image would proxy and re-encode through the console server
        <img alt="" className="h-full w-full object-cover" onError={onError} src={src ?? undefined} />
      )}
      {state === 'frame-crop' && region && (
        // biome-ignore lint/performance/noImgElement: a presigned R2 URL that next/image would proxy and re-encode through the console server
        <img alt="" className="absolute max-w-none" onError={onError} src={frameSrc ?? undefined} style={cropImageStyle(region)} />
      )}
      {state === 'pending' && (
        <div className="grid h-full place-items-center bg-gradient-to-r from-[#e7ebe3] via-[#f5f7f2] to-[#e7ebe3] text-[11px] text-ink/50 motion-safe:animate-pulse">
          Cropping frame{seconds != null ? ` ${formatClock(seconds)}` : ''}…
        </div>
      )}
      {state === 'missing' && (
        <div className="grid h-full place-items-center bg-[repeating-linear-gradient(45deg,#f4efe9,#f4efe9_8px,#efe7de_8px,#efe7de_16px)] p-2 text-center text-[11.5px] text-[#9b3518]">
          <span>
            <b>Image unavailable</b>
            <br />
            {failed ? 'The image failed to load.' : 'No stored image or frame for this item.'}
          </span>
        </div>
      )}
      {kind && (
        <span className="absolute left-1.5 top-1.5 flex items-center gap-1 rounded-full bg-white/90 px-2 py-0.5 text-[10.5px] font-semibold text-ink">
          <i className={`inline-block h-2 w-2 rounded-full ${KIND_COLOUR[kind]}`} />
          {KIND_LABEL[kind]}
        </span>
      )}
      {seconds != null && (
        <span className="absolute bottom-1.5 right-1.5 rounded-md bg-black/60 px-1.5 py-0.5 font-mono text-[10.5px] text-white">
          {formatClock(seconds)}
        </span>
      )}
    </div>
  );
}

export { EvidenceFrame as CropImage };
