// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useRef, useState } from 'react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Slider } from '@/components/ui/slider';
import type { FrameRegion } from '@/lib/evidence/frame-geometry';
import {
  dragRegion,
  pickSeconds,
  regionBox,
  usableRange,
  type FramePick,
  type FramePoint,
  type SecondsRange,
} from '@/lib/evidence/frame-picker';
import { formatClock } from '@/modules/reports/domain/normalize';

const percent = (fraction: number) => `${+(fraction * 100).toFixed(3)}%`;

/**
 * A dialog where the reviewer scrubs the video to a frame and drags a rectangle
 * on it. Use this crop cuts the rectangle from that frame on the server and
 * hands the JPEG back to the caller. It is held in the browser: nothing is
 * written to R2 until the draft is saved.
 */
export function EvidenceFramePicker({
  videoId,
  videoSrc,
  label,
  initialSeconds,
  range,
  onPick,
  onClose,
}: {
  videoId: string;
  videoSrc: string;
  label: string;
  initialSeconds: number;
  range: SecondsRange | null;
  onPick: (pick: FramePick) => void;
  onClose: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const dragOriginRef = useRef<FramePoint | null>(null);
  const [seconds, setSeconds] = useState(() => pickSeconds(initialSeconds, null, range));
  const [duration, setDuration] = useState<number | null>(null);
  const [drag, setDrag] = useState<{ from: FramePoint; to: FramePoint } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const region: FrameRegion | null = drag ? dragRegion(drag.from, drag.to) : null;
  const seen = usableRange(range);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose();
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [busy, onClose]);

  const seek = (value: number) => {
    const next = pickSeconds(value, duration, range);
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
    dragOriginRef.current = point;
    setDrag({ from: point, to: point });
  };
  const moveDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const from = dragOriginRef.current;
    if (from) setDrag({ from, to: pointOn(event) });
  };
  const finishDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    const from = dragOriginRef.current;
    if (from) setDrag({ from, to: pointOn(event) });
    dragOriginRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };
  const cancelDrag = (event: React.PointerEvent<HTMLDivElement>) => {
    dragOriginRef.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId);
  };

  const crop = async () => {
    if (!region) return;
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(`/api/reports/${encodeURIComponent(videoId)}/evidence-crop`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ timestampSeconds: seconds, region }),
      });
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.error ?? `The crop failed (${response.status})`);
      }
      const blob = await response.blob();
      onPick({ blob, previewUrl: URL.createObjectURL(blob), timestampSeconds: seconds, box: regionBox(region) });
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'The crop failed');
      setBusy(false);
    }
  };

  return (
    <Dialog
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
      open
    >
      <DialogContent
        aria-label={`Pick a frame for ${label}`}
        className="w-full max-w-[calc(100%-2rem)] gap-4 rounded-2xl bg-white p-5 shadow-xl sm:max-w-3xl"
        role="dialog"
      >
        <DialogHeader className="flex flex-row items-center justify-between gap-3 space-y-0 pr-6">
          <DialogTitle className="text-sm font-bold text-ink">Pick a frame for {label}</DialogTitle>
          <Badge className="font-mono text-[11px] text-muted-foreground" data-testid="frame-picker-time" variant="outline">
            {formatClock(seconds)}
          </Badge>
        </DialogHeader>
        <DialogDescription className="sr-only">
          Scrub to the frame, then drag a rectangle on it. The image is cut from that frame.
        </DialogDescription>

        <div className="relative mt-1 aspect-video select-none overflow-hidden rounded-xl bg-black">
          <video
            className="h-full w-full object-fill"
            muted
            onLoadedMetadata={(event) => {
              const length = event.currentTarget.duration;
              setDuration(Number.isFinite(length) && length > 0 ? length : null);
            }}
            playsInline
            preload="auto"
            ref={videoRef}
            src={videoSrc}
          />
          <div
            className="absolute inset-0 cursor-crosshair touch-none"
            data-testid="frame-picker-surface"
            onPointerCancel={cancelDrag}
            onPointerDown={startDrag}
            onPointerMove={moveDrag}
            onPointerUp={finishDrag}
          />
          {region && (
            <div
              className="pointer-events-none absolute border-2 border-white bg-white/15 shadow-[0_0_0_1px_rgba(0,0,0,0.6)]"
              data-testid="frame-picker-box"
              style={{ left: percent(region.x), top: percent(region.y), width: percent(region.w), height: percent(region.h) }}
            />
          )}
        </div>

        <Slider
          aria-label="Frame second"
          className="mt-2 w-full"
          disabled={duration === null || busy}
          max={seen === null ? (duration ?? 0) : Math.min(seen.last, duration ?? seen.last)}
          min={seen?.first ?? 0}
          onValueChange={([val]) => seek(val)}
          step={0.1}
          value={[seconds]}
        />
        <p className="text-[11px] text-muted-foreground">
          Scrub to the frame, then drag a rectangle on it. The image is cut from that frame.
        </p>
        {error && (
          <Alert className="mt-2" variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <DialogFooter className="mt-2 flex flex-row items-center justify-end gap-2 text-sm">
          <Button
            className="rounded-full border border-ink/20 font-semibold"
            disabled={busy}
            onClick={onClose}
            size="sm"
            type="button"
            variant="outline"
          >
            Cancel
          </Button>
          <Button
            className="rounded-full bg-ink font-semibold text-white hover:bg-ink/90 disabled:opacity-40"
            disabled={!region || busy}
            onClick={crop}
            size="sm"
            type="button"
          >
            {busy ? 'Cropping…' : 'Use this crop'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
