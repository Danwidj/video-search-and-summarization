// SPDX-License-Identifier: Apache-2.0

import type { CameraView } from '@/modules/reports/application/types';

export interface CameraOption {
  video: string;
  selectable: boolean;
  /** Why the camera cannot be picked; null when it can. */
  reason: string | null;
}

/**
 * The switcher's options. A camera of a video that has left the incident is history and cannot be picked; a camera
 * whose report does not pass the contract cannot be shown by the report panes. Cameras of removed videos are listed
 * (disabled) so an older version still says what it covered.
 */
export function cameraOptions(cameras: readonly CameraView[]): CameraOption[] {
  return cameras.map((camera) => {
    if (!camera.current) return { video: camera.video, selectable: false, reason: 'This video was removed from the incident' };
    if (!camera.valid) return { video: camera.video, selectable: false, reason: 'This camera has no valid report in this version' };
    return { video: camera.video, selectable: true, reason: null };
  });
}

/** The switcher is only useful when there is more than one camera to choose between. */
export const showCameraSwitcher = (cameras: readonly CameraView[]): boolean => cameras.length > 1;

/** The number of cameras of the version whose video is still in the incident. */
export const currentCameraCount = (cameras: readonly CameraView[]): number => cameras.filter((camera) => camera.current).length;
