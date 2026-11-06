// SPDX-License-Identifier: Apache-2.0
'use client';

import { type RefObject, useEffect, useRef, useState } from 'react';

import { cn } from '@/lib/utils';
import {
  containedBoxStyle,
  STILL_BOX_COLOUR,
  parseTrackSamples,
  type StillBox,
  stillBoxShows,
  type TrackSample,
  trackBoxAt,
} from '@/modules/reports/domain/track';

/** One tracked item the overlay draws: its name (shown as the box label, never its id), colour and either the console route its samples are read from or, for a draft's unsaved track, the samples themselves. */
export interface TrackedItem {
  id: string;
  label: string;
  colour: string;
  trackUrl: string | null;
  samples?: TrackSample[];
}

// Each track is read once per page load; a failed or malformed one is cached as empty, so it draws nothing and is not retried.
const loaded = new Map<string, Promise<TrackSample[]>>();
function loadTrack(url: string): Promise<TrackSample[]> {
  let pending = loaded.get(url);
  if (!pending) {
    pending = fetch(url)
      .then((response) => (response.ok ? response.json() : null))
      .then((body: { samples?: unknown } | null) => parseTrackSamples(body?.samples) ?? [])
      .catch(() => []);
    loaded.set(url, pending);
  }
  return pending;
}

/** The video's current second, read every frame while it plays (timeupdate alone moves a box only about four times a second). */
function usePlayhead(video: RefObject<HTMLVideoElement | null>): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const element = video.current;
    if (!element) return;
    let frame = 0;
    const read = () => setSeconds(element.currentTime);
    const tick = () => {
      read();
      frame = requestAnimationFrame(tick);
    };
    const play = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(tick);
    };
    const stop = () => {
      cancelAnimationFrame(frame);
      read();
    };
    read();
    if (!element.paused) play();
    element.addEventListener('play', play);
    element.addEventListener('pause', stop);
    element.addEventListener('ended', stop);
    element.addEventListener('seeked', read);
    element.addEventListener('timeupdate', read);
    return () => {
      cancelAnimationFrame(frame);
      element.removeEventListener('play', play);
      element.removeEventListener('pause', stop);
      element.removeEventListener('ended', stop);
      element.removeEventListener('seeked', read);
      element.removeEventListener('timeupdate', read);
    };
  }, [video]);
  return seconds;
}

/**
 * A box over the report player that follows each tracked person: the box at the playhead (interpolated between samples,
 * hidden outside the track's span), one colour per person with its name, the selected one emphasised. It never takes a
 * pointer event, so the player's own controls work through it.
 * An untracked item's box shows for a moment from its second (`stillBoxShows`), playing or paused; several can overlap.
 */
export function TrackOverlay({
  video,
  items,
  frameAspect,
  selectedId,
  stills = [],
}: {
  video: RefObject<HTMLVideoElement | null>;
  items: TrackedItem[];
  /** The video's own width / height. */
  frameAspect: number;
  selectedId: string | null;
  stills?: StillBox[];
}) {
  const seconds = usePlayhead(video);
  const tileRef = useRef<HTMLDivElement>(null);
  const [tileAspect, setTileAspect] = useState(frameAspect);
  const [tracks, setTracks] = useState<Record<string, TrackSample[]>>({});

  useEffect(() => {
    let live = true;
    for (const { trackUrl: url } of items) {
      if (!url) continue;
      void loadTrack(url).then((samples) => {
        if (live) setTracks((current) => (current[url] === samples ? current : { ...current, [url]: samples }));
      });
    }
    return () => {
      live = false;
    };
  }, [items]);

  useEffect(() => {
    const tile = tileRef.current;
    if (!tile) return;
    const measure = () => {
      if (tile.clientWidth > 0 && tile.clientHeight > 0) setTileAspect(tile.clientWidth / tile.clientHeight);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(tile);
    return () => observer.disconnect();
  }, []);

  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden" data-testid="track-overlay" ref={tileRef}>
      {stills
        .filter((still) => stillBoxShows(still, seconds))
        .map((still) => (
          <StillBoxMark frameAspect={frameAspect} key={still.id} selectedId={selectedId} still={still} tileAspect={tileAspect} />
        ))}
      {items.map((item) => {
        const samples = item.samples ?? (item.trackUrl ? tracks[item.trackUrl] : null);
        const style = samples ? containedBoxStyle(trackBoxAt(samples, seconds), frameAspect, tileAspect) : null;
        if (!style) return null;
        const selected = item.id === selectedId;
        const dimmed = selectedId !== null && !selected;
        return (
          <div
            className={cn(
              'absolute rounded-sm border-2 border-solid transition-opacity',
              selected && 'border-[3px]',
              dimmed && 'opacity-50',
            )}
            data-selected={selected ? 'true' : undefined}
            data-testid="track-box"
            data-track-item={item.id}
            key={item.id}
            style={{ ...style, borderColor: item.colour, boxShadow: selected ? `0 0 0 2px rgb(0 0 0 / 0.45)` : undefined }}
          >
            <span
              className={cn(
                'absolute -top-[1.35rem] -left-[2px] max-w-56 truncate rounded-sm px-1 py-px font-mono text-[10.5px] font-bold text-white',
                selected && 'text-[11.5px]',
              )}
              style={{ backgroundColor: item.colour }}
            >
              {item.label}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** The box of an untracked item: dashed, so it reads as a stored box and not a following one; selected and dimmed as a track is. */
function StillBoxMark({
  still,
  selectedId,
  frameAspect,
  tileAspect,
}: {
  still: StillBox;
  selectedId: string | null;
  frameAspect: number;
  tileAspect: number;
}) {
  const style = containedBoxStyle(still.box, frameAspect, tileAspect);
  if (!style) return null;
  const selected = still.id === selectedId;
  const dimmed = selectedId !== null && !selected;
  return (
    <div
      className={cn('absolute rounded-sm border-2 border-dashed transition-opacity', selected && 'border-[3px]', dimmed && 'opacity-50')}
      data-selected={selected ? 'true' : undefined}
      data-still-item={still.id}
      data-testid="still-box"
      style={{ ...style, borderColor: STILL_BOX_COLOUR, boxShadow: selected ? '0 0 0 2px rgb(0 0 0 / 0.45)' : undefined }}
    >
      <span
        className={cn(
          'absolute -top-[1.35rem] -left-[2px] max-w-56 truncate rounded-sm px-1 py-px font-mono text-[10.5px] font-bold text-black',
          selected && 'text-[11.5px]',
        )}
        style={{ backgroundColor: STILL_BOX_COLOUR }}
      >
        {still.label}
      </span>
    </div>
  );
}
