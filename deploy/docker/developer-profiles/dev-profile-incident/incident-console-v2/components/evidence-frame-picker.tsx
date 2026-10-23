// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useRef, useState } from 'react';

import { dragRegion, pickSeconds, regionBox, type FramePick, type FramePoint } from '@/lib/evidence/frame-picker';
import type { FrameRegion } from '@/lib/evidence/frame-geometry';
import { formatClock } from '@/lib/reports/normalize';

const percent = (fraction: number) => `${+(fraction * 100).toFixed(3)}%`;

/**
 * A dialog where the reviewer scrubs the video to a frame and drags a rectangle
 * on it. Save crops that rectangle from that frame on the server and hands the
 * new image back to the caller; nothing is written until the draft is saved.
 */
export function EvidenceFramePicker({ videoId, videoSrc, itemId, label, onPick, onClose }: {
  videoId: string;
  videoSrc: string;
  itemId: string;
  label: string;
  onPick: (pick: FramePick) => void;
  onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [seconds, setSeconds] = useState(0);
  const [duration, setDuration] = useState<number | null>(null);
  const [drag, setDrag] = useState<{ from: FramePoint; to: FramePoint } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const region: FrameRegion | null = drag ? dragRegion(drag.from, drag.to) : null;

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape' && !busy) onClose(); };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [busy, onClose]);

  const seek = (value: number) => {
    const next = pickSeconds(value, duration);
    setSeconds(next);
    if (videoRef.current) videoRef.current.currentTime = next;
  };

  // The surface covers the video exactly (object-fill), so a point maps to the same fraction of the frame.
  const pointOn = (event: React.PointerEvent<HTMLDivElement>): FramePoint => {
    const rect = event.currentTarget.getBoundingClientRect();
    return { x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height };
  };
  const startDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    const point = pointOn(event);
    setDrag({ from: point, to: point });
  };
  const moveDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    if (drag) setDrag({ from: drag.from, to: pointOn(event) });
  };

  const crop = async () => {
    if (!region) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/reports/${encodeURIComponent(videoId)}/evidence-crop`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ itemId, timestampSeconds: seconds, region }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.error ?? `The crop failed (${response.status})`);
      onPick({ image: body.image, imageUrl: body.imageUrl, timestampSeconds: seconds, box: regionBox(region) });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The crop failed');
      setBusy(false);
    }
  };

  return (
    <div aria-label={`Pick a frame for ${label}`} aria-modal="true" className="fixed inset-0 z-50 grid place-items-center bg-ink/40 p-4" role="dialog">
      <div className="w-full max-w-3xl rounded-2xl bg-white p-4 shadow-xl">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-bold">Pick a frame for {label}</h2>
          <span className="font-mono text-[11px] text-ink/50" data-testid="frame-picker-time">{formatClock(seconds)}</span>
        </div>

        <div className="relative mt-3 aspect-video select-none overflow-hidden rounded-xl bg-black">
          <video
            className="h-full w-full object-fill"
            muted
            onLoadedMetadata={(event) => { const length = event.currentTarget.duration; setDuration(Number.isFinite(length) && length > 0 ? length : null); }}
            playsInline
            preload="auto"
            ref={videoRef}
            src={videoSrc}
          />
          <div
            className="absolute inset-0 cursor-crosshair touch-none"
            data-testid="frame-picker-surface"
            onPointerDown={startDrag}
            onPointerMove={moveDrag}
          />
          {region && (
            <div
              className="pointer-events-none absolute border-2 border-white bg-white/15 shadow-[0_0_0_1px_rgba(0,0,0,0.6)]"
              data-testid="frame-picker-box"
              style={{ left: percent(region.x), top: percent(region.y), width: percent(region.w), height: percent(region.h) }}
            />
          )}
        </div>

        <input
          aria-label="Frame second"
          className="mt-3 w-full"
          disabled={duration === null || busy}
          max={duration ?? 0}
          min={0}
          onChange={(event) => seek(Number(event.target.value))}
          step={0.1}
          type="range"
          value={seconds}
        />
        <p className="mt-2 text-[11px] text-ink/50">Scrub to the frame, then drag a rectangle on it. The image is cut from that frame.</p>
        {error && <p className="mt-2 rounded-xl border border-clay/30 bg-clay/5 px-3 py-2 text-xs text-[#9b3518]" role="alert">{error}</p>}

        <div className="mt-3 flex items-center justify-end gap-2 text-sm">
          <button className="rounded-full border border-ink/20 bg-white px-3 py-1 font-semibold text-ink disabled:opacity-40" disabled={busy} onClick={onClose} type="button">Cancel</button>
          <button className="rounded-full bg-ink px-3 py-1 font-semibold text-white disabled:opacity-40" disabled={!region || busy} onClick={crop} type="button">{busy ? 'Cropping…' : 'Use this crop'}</button>
        </div>
      </div>
    </div>
  );
}
