// SPDX-License-Identifier: Apache-2.0

/**
 * The one hover and keyboard-focus style for a card that opens something: a blue border (not the Official teal or the
 * Generate green), a stronger shadow, and a lift with a slight scale. The lift is dropped under prefers-reduced-motion; the
 * colour and shadow stay. CARD_HOVER_STILL is the same without the lift, for a card inside a scrolling strip that would clip it. Put it on the Card, and CARD_ZOOM on the media inside its clipped frame.
 */
export const CARD_HOVER_STILL =
  'transition duration-200 ease-out hover:border-card-hover hover:ring-card-hover/70 hover:shadow-xl hover:shadow-card-hover/25 focus-visible:border-card-hover focus-visible:ring-2 focus-visible:ring-card-hover focus-visible:shadow-xl focus-visible:shadow-card-hover/25';

export const CARD_HOVER = `${CARD_HOVER_STILL} motion-safe:hover:-translate-y-1 motion-safe:hover:scale-[1.02] motion-safe:focus-visible:-translate-y-1 motion-safe:focus-visible:scale-[1.02]`;

/** A small zoom of the thumbnail inside its overflow-hidden frame, when the card is hovered or focused. */
export const CARD_ZOOM =
  'transition-transform duration-200 ease-out motion-safe:group-hover:scale-105 motion-safe:group-focus-visible:scale-105';
