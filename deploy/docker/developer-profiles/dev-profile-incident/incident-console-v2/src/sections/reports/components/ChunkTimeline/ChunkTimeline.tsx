// SPDX-License-Identifier: Apache-2.0
'use client';

import { useEffect, useRef } from 'react';

import { cn } from '@/lib/utils';
import { activeChunkIndex, type ChunkWindow } from '@/modules/reports/domain/chunk-timeline';
import { formatClock } from '@/modules/reports/domain/normalize';

/**
 * The run's caption pass under the video: one row per window with its time and
 * full caption. A click moves the playhead to the window's start; the window
 * playing now is highlighted and kept in view inside the strip (never by
 * scrolling the page). Rendered only when the run has a chunk timeline.
 */
export function ChunkTimeline({
  windows,
  currentTime,
  onSeek,
}: {
  windows: ChunkWindow[];
  currentTime: number;
  onSeek: (window: ChunkWindow) => void;
}) {
  const listRef = useRef<HTMLOListElement>(null);
  const active = activeChunkIndex(windows, currentTime);

  useEffect(() => {
    const list = listRef.current;
    const row = active < 0 ? null : list?.children[active];
    if (!list || !(row instanceof HTMLElement)) return;
    // Scroll the strip itself: scrollIntoView would also scroll the page.
    const top = row.offsetTop;
    const bottom = top + row.offsetHeight;
    // A window taller than the strip is aligned by its top, so its time and first lines show.
    if (top < list.scrollTop) list.scrollTo({ top, behavior: 'smooth' });
    else if (bottom > list.scrollTop + list.clientHeight)
      list.scrollTo({ top: Math.min(top, bottom - list.clientHeight), behavior: 'smooth' });
  }, [active]);

  return (
    <section aria-label="Caption timeline" className="border-b border-border bg-card" data-testid="chunk-timeline">
      <div className="flex items-baseline gap-3 px-5 pt-2 pb-1 sm:px-8">
        <h2 className="font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-muted-foreground">Caption timeline</h2>
        <span className="text-xs text-muted-foreground">
          Model captions of {windows.length} {windows.length === 1 ? 'window' : 'windows'}, written before the report: context, not
          evidence. Select one to jump there.
        </span>
      </div>
      <ol className="relative m-0 max-h-44 list-none overflow-y-auto px-3 pb-2 sm:px-6" ref={listRef}>
        {windows.map((window, index) => (
          <li key={`${window.startSeconds}-${window.endSeconds}`}>
            <button
              aria-current={index === active ? 'true' : undefined}
              className={cn(
                'grid w-full grid-cols-[6.5rem_1fr] gap-4 rounded-md border-l-2 border-transparent px-2 py-1.5 text-left text-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                index === active && 'border-primary bg-primary/10 hover:bg-primary/15',
              )}
              data-testid="chunk-window"
              onClick={() => onSeek(window)}
              type="button"
            >
              <span
                className={cn(
                  'pt-px font-mono text-xs tabular-nums text-muted-foreground',
                  index === active && 'font-semibold text-primary',
                )}
              >
                {formatClock(window.startSeconds)}–{formatClock(window.endSeconds)}
              </span>
              <span className="whitespace-pre-line leading-5 text-foreground/80">{window.caption}</span>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}
