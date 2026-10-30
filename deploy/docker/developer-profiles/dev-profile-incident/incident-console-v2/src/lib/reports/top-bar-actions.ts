// SPDX-License-Identifier: Apache-2.0

import type { IncidentReportView } from '@/modules/reports/application/types';

export interface TopBarAction {
  enabled: boolean;
  /** Why the action is unavailable; null when it is enabled. */
  reason: string | null;
}

export interface TopBarActions {
  reanalyse: TopBarAction;
  merge: TopBarAction;
  remove: TopBarAction;
  regenerate: TopBarAction;
}

const NO_CAMERA = 'No camera of this version can be shown. Open another version or regenerate the report.';
const NO_VIDEOS = 'This incident has no videos.';

const enabled: TopBarAction = { enabled: true, reason: null };

/**
 * Which report-page actions are available. Re-analyse and Remove act on the camera being viewed, so they need a camera
 * the page can show. Merge and Regenerate act on the incident's videos, so they stay available without one.
 */
export function topBarActions(view: Pick<IncidentReportView, 'report' | 'incidentVideos'>): TopBarActions {
  const onCamera: TopBarAction = view.report ? enabled : { enabled: false, reason: NO_CAMERA };
  const onIncident: TopBarAction = view.incidentVideos.length > 0 ? enabled : { enabled: false, reason: NO_VIDEOS };
  return { reanalyse: onCamera, remove: onCamera, merge: onIncident, regenerate: onIncident };
}
