// SPDX-License-Identifier: Apache-2.0
'use client';

import type { ReactNode } from 'react';

/**
 * The evidence carousel, shared by View and Edit: one horizontal rail of cards with the same gutter and spacing. `lanes`
 * lays the cards out as a grid of rows instead (Edit's saved and draft lanes).
 */
export function EvidenceCarousel({ children, label, lanes = false }: { children: ReactNode; label: string; lanes?: boolean }) {
  return (
    <section aria-label={label} className="relative px-4 pt-3 pb-1">
      <div
        className={
          lanes
            ? 'grid auto-cols-[min(15.5rem,calc(100vw-4rem))] grid-cols-[3.25rem] grid-flow-col grid-rows-[auto_auto] gap-x-3 gap-y-2 overflow-x-auto pb-3'
            : 'flex snap-x snap-mandatory gap-3 overflow-x-auto pb-3'
        }
      >
        {children}
      </div>
    </section>
  );
}
