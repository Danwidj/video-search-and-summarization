// SPDX-License-Identifier: Apache-2.0
'use client';

import { type RefObject, useLayoutEffect, useState } from 'react';

/** Where the active item sits inside its root, in CSS pixels. */
export interface IndicatorBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * Measures the item marked `data-indicator-key={activeKey}` inside `root`, so one shared highlight can slide between items.
 * The first measurement is made before paint and the highlight mounts already in place, so nothing slides on first render.
 * It measures again whenever the root's size changes, so a window resize keeps it on the active item.
 */
export function useSlidingIndicator(root: RefObject<HTMLElement | null>, activeKey: string): IndicatorBox | null {
  const [box, setBox] = useState<IndicatorBox | null>(null);

  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    const measure = () => {
      const item = Array.from(element.querySelectorAll<HTMLElement>('[data-indicator-key]')).find(
        (candidate) => candidate.dataset.indicatorKey === activeKey,
      );
      if (!item) {
        setBox(null);
        return;
      }
      const frame = element.getBoundingClientRect();
      const rect = item.getBoundingClientRect();
      setBox({ left: rect.left - frame.left, top: rect.top - frame.top, width: rect.width, height: rect.height });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [root, activeKey]);

  return box;
}
