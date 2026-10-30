// SPDX-License-Identifier: Apache-2.0

// How a structured match reason (the agent's `kind`) is drawn: which icon family it belongs to and
// whether it is a strong reason (place and event type carry the score) or a soft one (a dashed hint,
// or a difference). An unknown kind from a newer agent still renders, as a soft chip.

export type ReasonGroup = 'place' | 'type' | 'time' | 'other';

export interface ReasonChipStyle {
  group: ReasonGroup;
  strong: boolean;
}

const STRONG = new Set(['same_event_type', 'same_place', 'similar_place']);

export function reasonChipStyle(kind: string): ReasonChipStyle {
  const group: ReasonGroup = kind.endsWith('event_type')
    ? 'type'
    : kind.endsWith('place') || kind === 'place_unknown'
      ? 'place'
      : kind.startsWith('time_')
        ? 'time'
        : 'other';
  return { group, strong: STRONG.has(kind) };
}
