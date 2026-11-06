// SPDX-License-Identifier: Apache-2.0

'use client';

import { ChevronLeftIcon, ChevronRightIcon } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';

import { MutedVideo } from '@/components/muted-video';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Slider } from '@/components/ui/slider';
import { boxRegion } from '@/lib/evidence/frame-geometry';
import { movePick, pickCeiling, type PickSeed, roundPick } from '@/lib/evidence/image-pick';
import { formatClock } from '@/modules/reports/domain/normalize';
import type { Box, ImagePick } from '@/modules/reports/domain/reviewer-item';
import type { EvidenceItemType } from '@/modules/reports/domain/revision';
import { BoxCanvas } from '@/sections/evidence/components/BoxTool/BoxCanvas';

const KIND_LABEL: Record<EvidenceItemType, string> = { entity: 'Entity', instrument: 'Instrument', asset: 'Asset' };
const STEP_SECONDS = 0.1;

/** The crop the server will store for a box at a second, read through the crop route (nothing is written). */
async function fetchCrop(videoId: string, seconds: number, box: Box, signal: AbortSignal): Promise<Blob> {
  const response = await fetch(`/api/reports/${encodeURIComponent(videoId)}/evidence-crop`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ timestampSeconds: seconds, region: boxRegion(box) }),
    signal,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { error?: string } | null;
    throw new Error(body?.error ?? `The crop failed (${response.status})`);
  }
  return response.blob();
}

/**
 * Set image (Edit mode): choose a frame of the report's video, drag on it to draw the crop, check the result, and put it on
 * the draft. Only the item's evidence image changes; Done hands back the second and box, and Save cuts the image there.
 */
export function EvidenceImagePicker({
  videoId,
  videoSrc,
  name,
  itemId = null,
  kind,
  seed,
  onClose,
  onDone,
}: {
  videoId: string;
  videoSrc: string;
  name: string;
  itemId?: string | null;
  kind: EvidenceItemType;
  /** Where the dialog opens: the item's current image second and box (no box when it has none). */
  seed: PickSeed;
  onClose: () => void;
  onDone: (pick: ImagePick) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [seconds, setSeconds] = useState(() => roundPick(Math.max(0, seed.seconds)));
  const [box, setBox] = useState<Box | null>(seed.box);
  const [duration, setDuration] = useState<number | null>(null);
  const [cropUrl, setCropUrl] = useState<string | null>(null);
  const [cropping, setCropping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Show the crop Save will store for this frame and box, read through the crop route.
  useEffect(() => {
    setCropUrl(null);
    setError(null);
    if (!box) return;
    const controller = new AbortController();
    let url: string | null = null;
    setCropping(true);
    fetchCrop(videoId, seconds, box, controller.signal)
      .then((blob) => {
        url = URL.createObjectURL(blob);
        setCropUrl(url);
      })
      .catch((cause) => {
        if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'The crop failed');
      })
      .finally(() => {
        if (!controller.signal.aborted) setCropping(false);
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [videoId, seconds, box]);

  const moveTo = (next: number) => {
    if (next === seconds) return;
    setSeconds(next);
    setBox(null);
    if (videoRef.current) videoRef.current.currentTime = next;
  };

  const ready = box !== null && cropUrl !== null && !cropping;
  const ceiling = pickCeiling(duration);
  const heading = [itemId, name].filter(Boolean).join(' · ');

  return (
    <Dialog
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      open
    >
      <DialogContent
        aria-label={`Set image for ${name}`}
        className="max-h-[calc(100vh-2rem)] w-full max-w-[calc(100%-2rem)] gap-0 overflow-y-auto rounded-2xl bg-white p-0 shadow-xl sm:max-w-4xl"
        onOpenAutoFocus={(event) => event.preventDefault()}
        role="dialog"
      >
        <DialogHeader className="relative gap-2 border-b border-border/70 bg-muted/40 px-6 py-5 pr-24 text-left">
          <DialogTitle className="text-lg font-bold tracking-tight text-foreground">Set image</DialogTitle>
          <p className="truncate text-sm font-semibold text-foreground" data-testid="image-item-title">
            {heading}
          </p>
          <fieldset aria-label="Item details" className="flex flex-wrap items-center gap-1.5 border-0 p-0">
            <Badge className="text-[10px]" variant="outline">
              {KIND_LABEL[kind]}
            </Badge>
            <Badge className="font-mono text-[10px] text-muted-foreground" variant="outline">
              {formatClock(seconds)}
            </Badge>
          </fieldset>
        </DialogHeader>
        <div className="flex flex-col gap-3 p-5">
          <DialogDescription className="text-xs leading-relaxed text-muted-foreground">
            Pick the frame, then drag on it to draw the crop around {name || 'the item'}. Only the evidence image changes; its track and
            text stay as they are.
          </DialogDescription>
          {error && (
            <Alert variant="destructive">
              <AlertDescription data-testid="image-picker-error">{error}</AlertDescription>
            </Alert>
          )}
          <div className="grid gap-4 sm:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <div className="min-w-0 space-y-2">
              <BoxCanvas box={box} drawable onDraw={setBox} testId="image-picker-frame">
                <MutedVideo
                  aria-label={`Frame at ${formatClock(seconds)}`}
                  className="h-full w-full object-fill"
                  onLoadedMetadata={(event) => {
                    const length = event.currentTarget.duration;
                    setDuration(Number.isFinite(length) && length > 0 ? length : null);
                    event.currentTarget.currentTime = seconds;
                  }}
                  playsInline
                  preload="auto"
                  ref={videoRef}
                  src={videoSrc}
                />
              </BoxCanvas>
              <div className="flex items-center gap-2">
                <Button
                  aria-label="Back 0.1 s"
                  disabled={duration === null}
                  onClick={() => moveTo(movePick(seconds, -STEP_SECONDS, duration))}
                  size="icon-sm"
                  type="button"
                  variant="ghost"
                >
                  <ChevronLeftIcon />
                </Button>
                <Slider
                  aria-label="Frame second"
                  data-testid="image-picker-slider"
                  disabled={duration === null}
                  max={ceiling ?? 0}
                  min={0}
                  onValueChange={([val]) => moveTo(movePick(val, 0, duration))}
                  step={STEP_SECONDS}
                  value={[Math.min(seconds, ceiling ?? seconds)]}
                />
                <Button
                  aria-label="Forward 0.1 s"
                  disabled={duration === null}
                  onClick={() => moveTo(movePick(seconds, STEP_SECONDS, duration))}
                  size="icon-sm"
                  type="button"
                  variant="ghost"
                >
                  <ChevronRightIcon />
                </Button>
                <span className="font-mono text-xs text-ink" data-testid="image-picker-clock">
                  {seconds.toFixed(1)} s<span className="text-ink-caption"> / {(duration ?? 0).toFixed(1)} s</span>
                </span>
              </div>
              <p className="text-[11px] text-muted-foreground">
                {box ? 'Drag again to redraw the crop.' : 'Drag on the frame to draw the crop. Moving to another frame clears it.'}
              </p>
            </div>
            <div className="min-w-0 space-y-2" data-testid="image-picker-result">
              <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">Evidence image</p>
              <div className="relative grid aspect-video place-items-center overflow-hidden rounded-xl border border-border bg-muted/30">
                {cropUrl ? (
                  // biome-ignore lint/performance/noImgElement: a blob URL of the crop the browser just read; next/image cannot optimise it
                  <img
                    alt={`Crop of ${name}`}
                    className="absolute inset-0 size-full object-contain"
                    data-testid="image-picker-crop"
                    src={cropUrl}
                  />
                ) : (
                  <span className="px-4 text-center text-xs text-muted-foreground">
                    {cropping ? 'Cutting the crop…' : 'The crop appears here once you draw it.'}
                  </span>
                )}
              </div>
            </div>
          </div>
        </div>
        <DialogFooter className="flex flex-row items-center justify-end gap-2 border-t border-border/70 px-5 py-3 text-sm">
          <Button className="rounded-full border border-ink/20 font-semibold" onClick={onClose} size="sm" type="button" variant="outline">
            Cancel
          </Button>
          <Button
            className="rounded-full bg-ink font-semibold text-white hover:bg-ink/90 disabled:opacity-40"
            data-testid="image-picker-done"
            disabled={!ready}
            onClick={() => box && onDone({ seconds, box })}
            size="sm"
            type="button"
          >
            Use this image
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
