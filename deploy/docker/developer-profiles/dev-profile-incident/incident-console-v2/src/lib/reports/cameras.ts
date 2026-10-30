// SPDX-License-Identifier: Apache-2.0

import type { CameraView } from '@/modules/reports/application/types';

export interface CameraOption {
  video: string;
  selectable: boolean;
  /** Why the camera cannot be picked; null when it can. */
  reason: string | null;
  /** The short tag the switcher shows on a disabled camera; null when it can be picked. */
  badge: string | null;
}

/**
 * The switcher's options. A camera of a video that has left the incident is history and cannot be picked; a video the
 * open version does not cover has no report in it yet; a camera whose report does not pass the contract cannot be shown
 * by the report panes. Disabled cameras stay listed so the switcher says what the incident and the version cover.
 */
export function cameraOptions(cameras: readonly CameraView[]): CameraOption[] {
  return cameras.map((camera) => {
    if (!camera.current)
      return { video: camera.video, selectable: false, reason: 'This video was removed from the incident', badge: 'removed' };
    if (!camera.inVersion)
      return {
        video: camera.video,
        selectable: false,
        reason: 'This video is not in this version. Regenerate the report to include it.',
        badge: 'not in this version',
      };
    if (!camera.valid)
      return { video: camera.video, selectable: false, reason: 'This camera has no valid report in this version', badge: 'unavailable' };
    return { video: camera.video, selectable: true, reason: null, badge: null };
  });
}

/** The number of videos the open version covers that are still in the incident. */
export const currentCameraCount = (cameras: readonly CameraView[]): number =>
  cameras.filter((camera) => camera.current && camera.inVersion).length;

/** "2 of 3 videos in v3": how many of the incident's videos the open version covers. */
export function versionCoverageLabel(coveredVideos: number, incidentVideos: number, revisionNo: number): string {
  return `${coveredVideos} of ${incidentVideos} ${incidentVideos === 1 ? 'video' : 'videos'} in v${revisionNo}`;
}

/**
 * True when the incident overview already says the camera's summary: an incident of one camera has no other camera to
 * summarise, so the overview and the camera report carry the same text. A summary that differs (a reviewer edited one
 * of them) stays visible.
 */
export function repeatsOverviewSummary(
  cameras: readonly CameraView[],
  overviewDescription: string | null,
  cameraDescription: string | null,
): boolean {
  if (cameras.filter((camera) => camera.inVersion).length !== 1 || !overviewDescription || !cameraDescription) return false;
  return overviewDescription.trim() === cameraDescription.trim();
}
