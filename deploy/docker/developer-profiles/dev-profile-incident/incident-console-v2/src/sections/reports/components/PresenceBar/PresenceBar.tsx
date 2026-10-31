// SPDX-License-Identifier: Apache-2.0
'use client';

import type { MouseEvent } from 'react';

import { formatClock } from '@/modules/reports/domain/normalize';
import { presenceRegion, presenceSeekSeconds } from '@/modules/reports/domain/track';

/**
 * Where a tracked person is on screen, drawn over the whole clip: the track's span in its colour. A click seeks the player
 * to the second under the pointer (a click beside the span still seeks there). Rendered only with a known clip length.
 */
export function PresenceBar({
  firstSeconds,
  lastSeconds,
  durationSeconds,
  colour,
  label,
  onSeek,
  caption = true,
}: {
  firstSeconds: number;
  lastSeconds: number;
  durationSeconds: number | null;
  colour: string;
  /** What the span belongs to, for the accessible name. */
  label: string;
  onSeek: (seconds: number) => void;
  /** Print the span under the bar; off where the span is already written beside it. */
  caption?: boolean;
}) {
  const region = presenceRegion(firstSeconds, lastSeconds, durationSeconds);
  if (!region || durationSeconds === null) return null;
  const span = `${formatClock(firstSeconds)}–${formatClock(lastSeconds)}`;
  const seek = (event: MouseEvent<HTMLButtonElement>) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    // A keyboard press has no pointer position: it plays from the start of the span.
    const fraction = event.detail === 0 || bounds.width <= 0 ? region.left : (event.clientX - bounds.left) / bounds.width;
    onSeek(presenceSeekSeconds(fraction, durationSeconds));
  };
  return (
    <div className="flex flex-col gap-1" data-testid="presence-bar">
      <button
        aria-label={`Tracked on screen ${span}: select to play ${label} from there`}
        className="relative h-2.5 w-full cursor-pointer overflow-hidden rounded-full bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        onClick={seek}
        title={`Tracked on screen ${span}`}
        type="button"
      >
        <span
          className="absolute inset-y-0 rounded-full"
          data-testid="presence-span"
          style={{ left: `${+(region.left * 100).toFixed(3)}%`, width: `${+(region.width * 100).toFixed(3)}%`, backgroundColor: colour }}
        />
      </button>
      {caption && <span className="font-mono text-[10.5px] text-muted-foreground">Tracked {span}</span>}
    </div>
  );
}
