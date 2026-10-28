// SPDX-License-Identifier: Apache-2.0

export type StageKey = 'idle' | 'uploading' | 'preparing' | 'analyzing' | 'saving' | 'complete' | 'error';

export const stageLabels: Array<{ key: StageKey; label: string }> = [
  { key: 'uploading', label: 'Uploading video' },
  { key: 'preparing', label: 'Preparing secure access' },
  { key: 'analyzing', label: 'Understanding the incident' },
  { key: 'saving', label: 'Structuring and saving report' },
  { key: 'complete', label: 'Report ready' },
];

export const stageOrder: Record<StageKey, number> = {
  idle: -1,
  uploading: 0,
  preparing: 1,
  analyzing: 2,
  saving: 3,
  complete: 4,
  error: -1,
};

export function getStageProgress(stage: StageKey, uploadProgress = 0, lastActiveStage?: StageKey): number {
  switch (stage) {
    case 'uploading':
      return Math.max(2, Math.min(20, Math.round((uploadProgress / 100) * 20)));
    case 'preparing':
      return 40;
    case 'analyzing':
      return 60;
    case 'saving':
      return 80;
    case 'complete':
      return 100;
    case 'error':
      if (lastActiveStage && lastActiveStage !== 'idle' && lastActiveStage !== 'error') {
        return getStageProgress(lastActiveStage, uploadProgress);
      }
      return 0;
    default:
      return 0;
  }
}

export function getStageAnnouncement(stage: StageKey, uploadProgress = 0, error: string | null = null): string {
  switch (stage) {
    case 'uploading':
      return `Stage 1 of 5: Uploading video${uploadProgress > 0 ? ` (${uploadProgress}%)` : ''}.`;
    case 'preparing':
      return 'Stage 2 of 5: Preparing secure access.';
    case 'analyzing':
      return 'Stage 3 of 5: Understanding the incident.';
    case 'saving':
      return 'Stage 4 of 5: Structuring and saving report.';
    case 'complete':
      return 'Stage 5 of 5: Report ready. Analysis complete.';
    case 'error':
      return `Analysis failed: ${error || 'An error occurred during analysis.'}`;
    default:
      return '';
  }
}
