// SPDX-License-Identifier: Apache-2.0

import type { IncidentSummary } from '@/modules/reports/domain/IncidentReportRepository';

/** The part of a library entry the merge list needs. */
export type MergeCandidateSource = Pick<IncidentSummary, 'incidentId' | 'title' | 'incidentType' | 'videoCount' | 'firstVideoName'>;

export interface MergeCandidate {
  incidentId: number;
  /** "Incident 9 · Unauthorised entry" */
  label: string;
  /** "gate-cam.mp4 · 1 video" */
  detail: string;
  videoCount: number;
}

const videosText = (count: number) => `${count} ${count === 1 ? 'video' : 'videos'}`;

/** Every incident except the one being merged away and any that holds no videos, newest ids first, labelled for the chooser. */
export function mergeCandidates(items: readonly MergeCandidateSource[], sourceIncidentId: number): MergeCandidate[] {
  return items
    .filter((item) => item.incidentId !== sourceIncidentId && item.videoCount > 0)
    .sort((a, b) => b.incidentId - a.incidentId)
    .map((item) => {
      const name = item.title || item.incidentType;
      const first = item.firstVideoName ? `${item.firstVideoName}${item.videoCount > 1 ? ` +${item.videoCount - 1} more` : ''} · ` : '';
      return {
        incidentId: item.incidentId,
        label: name ? `Incident ${item.incidentId} · ${name}` : `Incident ${item.incidentId}`,
        detail: `${first}${videosText(item.videoCount)}`,
        videoCount: item.videoCount,
      };
    });
}

/** How many videos the target holds once the source's videos have moved in. */
export const mergedVideoCount = (target: Pick<MergeCandidate, 'videoCount'>, sourceVideoCount: number): number =>
  target.videoCount + sourceVideoCount;

export const pluralVideos = videosText;
