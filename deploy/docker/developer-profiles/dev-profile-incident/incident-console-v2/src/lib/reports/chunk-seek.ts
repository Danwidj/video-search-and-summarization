// SPDX-License-Identifier: Apache-2.0

// Seeking from the caption timeline: move the playhead to a window's start and
// leave playback as it was (a paused video stays paused, a playing one plays on).

import type { ChunkWindow } from '@/modules/reports/domain/chunk-timeline';

/** The part of an HTMLVideoElement a seek touches. */
export interface Playhead {
  currentTime: number;
}

export function seekToWindow(video: Playhead | null, window: ChunkWindow): void {
  if (!video) return;
  video.currentTime = window.startSeconds;
}
