// SPDX-License-Identifier: Apache-2.0
'use client';

import { useEffect, useState, type RefObject } from 'react';

const HOVER_DELAY_MS = 300;

/** Signed links by video for this page load; a failed fetch is dropped so the next hover retries. */
const links = new Map<string, Promise<string | null>>();
/** Stops the preview now playing, so only one plays at a time. */
let stopActive: (() => void) | null = null;

function previewLink(videoId: string): Promise<string | null> {
  let link = links.get(videoId);
  if (!link) {
    link = fetch(`/api/reports/${encodeURIComponent(videoId)}/preview`)
      .then((response) => (response.ok ? response.json() : null))
      .then((body: { url?: string } | null) => body?.url ?? null)
      .catch(() => null);
    links.set(videoId, link);
    void link.then((url) => {
      if (!url) links.delete(videoId);
    });
  }
  return link;
}

/**
 * The video link to play while the pointer rests on the card holding `anchor` (its closest [data-card]), else null.
 * Starts after a short rest, so moving across cards loads nothing; never on touch or under reduced motion.
 */
export function useHoverPreview(anchor: RefObject<HTMLElement | null>, videoId: string | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    const card = anchor.current?.closest('[data-card]');
    if (!card || !videoId) return;
    if (!window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    let timer: ReturnType<typeof setTimeout> | undefined;
    let token = 0;
    const stop = () => {
      clearTimeout(timer);
      token += 1;
      setUrl(null);
      if (stopActive === stop) stopActive = null;
    };
    const enter = (event: Event) => {
      if ((event as PointerEvent).pointerType !== 'mouse') return;
      clearTimeout(timer);
      timer = setTimeout(() => {
        const mine = ++token;
        void previewLink(videoId).then((link) => {
          if (mine !== token || !link) return;
          if (stopActive && stopActive !== stop) stopActive();
          stopActive = stop;
          setUrl(link);
        });
      }, HOVER_DELAY_MS);
    };
    card.addEventListener('pointerenter', enter);
    card.addEventListener('pointerleave', stop);
    return () => {
      card.removeEventListener('pointerenter', enter);
      card.removeEventListener('pointerleave', stop);
      stop();
    };
  }, [anchor, videoId]);

  return url;
}
