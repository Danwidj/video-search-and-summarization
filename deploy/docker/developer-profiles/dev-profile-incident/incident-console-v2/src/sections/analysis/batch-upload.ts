// SPDX-License-Identifier: Apache-2.0

/** The four stages every file of a batch passes through, in order. */
export const BATCH_STAGES = ['upload', 'analyse', 'report', 'matches'] as const;
export type BatchStage = (typeof BATCH_STAGES)[number];

export const batchStageLabels: Record<BatchStage, string> = {
  upload: 'Upload',
  analyse: 'Analyse',
  report: 'Build report',
  matches: 'Check matches',
};

export type BatchStatus = 'queued' | 'running' | 'failed' | 'done';

export interface BatchItem {
  /** Local key; the stored name is only known after the upload. */
  key: string;
  name: string;
  size: number;
  status: BatchStatus;
  /** The stage running now, or the one that failed. */
  stage: BatchStage;
  /** 0 to 100 while the upload runs. */
  uploadProgress: number;
  error: string | null;
  /** What earlier stages produced, kept so a retry resumes where the file stopped. */
  uploaded: { sensorId: string; filePath: string; filename: string } | null;
  analysed: { incidentId: number } | null;
  built: boolean;
  /** Suggested matches found for the incident; null until the last stage ends. */
  matches: number | null;
}

export interface BatchDeps {
  upload(file: File, onProgress: (progress: number) => void): Promise<{ sensorId: string; filePath: string; filename: string }>;
  /** Finishes the upload on the agent. */
  complete(uploaded: { sensorId: string; filename: string }): Promise<void>;
  analyse(input: { uploaded: { sensorId: string; filePath: string; filename: string }; model: string }): Promise<{ incidentId: number }>;
  build(incidentId: number): Promise<void>;
  evaluate(incidentId: number): Promise<{ suggestions: number }>;
}

export function newBatchItem(file: File, key: string): BatchItem {
  return {
    key,
    name: file.name,
    size: file.size,
    status: 'queued',
    stage: 'upload',
    uploadProgress: 0,
    error: null,
    uploaded: null,
    analysed: null,
    built: false,
    matches: null,
  };
}

/** 0 to 100 for one file: each stage is worth a quarter, the upload fills its share as it goes. */
export function itemProgress(item: BatchItem): number {
  if (item.status === 'done') return 100;
  if (item.status === 'queued') return 0;
  const index = BATCH_STAGES.indexOf(item.stage);
  const within = item.stage === 'upload' && item.status === 'running' ? item.uploadProgress / 100 : 0.5;
  return Math.max(2, Math.round(((index + (item.status === 'failed' ? 0.5 : within)) / BATCH_STAGES.length) * 100));
}

export interface BatchSummary {
  total: number;
  done: number;
  failed: number;
  running: number;
  /** Percent of files that are done. */
  percent: number;
  settled: boolean;
}

export function summariseBatch(items: BatchItem[]): BatchSummary {
  const done = items.filter((item) => item.status === 'done').length;
  const failed = items.filter((item) => item.status === 'failed').length;
  const running = items.length - done - failed;
  return {
    total: items.length,
    done,
    failed,
    running,
    percent: items.length ? Math.round((done / items.length) * 100) : 0,
    settled: items.length > 0 && running === 0,
  };
}

const failureMessage = (error: unknown): string => (error instanceof Error && error.message ? error.message : 'The step failed');

/** Whether an analysis refusal means the upload's video row already exists (an earlier attempt got that far). */
export const isAlreadyStored = (error: unknown): boolean => /already exists/i.test(failureMessage(error));

/**
 * Runs one file through every stage it has not finished, reporting each change through `update`.
 * It never throws: a failure is recorded on the item at the stage that failed, so a sibling file
 * is unaffected and a retry resumes from that stage.
 */
export async function runBatchItem(
  file: File,
  start: BatchItem,
  model: string,
  deps: BatchDeps,
  update: (change: Partial<BatchItem>) => void,
): Promise<void> {
  let item = start;
  const set = (change: Partial<BatchItem>) => {
    item = { ...item, ...change };
    update(change);
  };
  let stage: BatchStage = item.uploaded ? (item.analysed ? (item.built ? 'matches' : 'report') : 'analyse') : 'upload';
  try {
    set({ status: 'running', error: null });
    if (!item.uploaded) {
      set({ stage: 'upload', uploadProgress: 0 });
      const uploaded = await deps.upload(file, (uploadProgress) => set({ uploadProgress }));
      await deps.complete(uploaded);
      set({ uploaded, name: uploaded.filename });
    }
    const uploaded = item.uploaded as NonNullable<BatchItem['uploaded']>;
    if (!item.analysed) {
      stage = 'analyse';
      set({ stage });
      set({ analysed: await deps.analyse({ uploaded, model }) });
    }
    const incidentId = (item.analysed as NonNullable<BatchItem['analysed']>).incidentId;
    if (!item.built) {
      stage = 'report';
      set({ stage });
      await deps.build(incidentId);
      set({ built: true });
    }
    stage = 'matches';
    set({ stage });
    const { suggestions } = await deps.evaluate(incidentId);
    set({ status: 'done', matches: suggestions });
  } catch (error) {
    update({ status: 'failed', stage, error: failureMessage(error) });
  }
}

/** Runs `task` over every item with at most `limit` in flight; a rejection never stops the others. */
export async function runPool<T>(items: T[], limit: number, task: (item: T) => Promise<void>): Promise<void> {
  const queue = [...items];
  const worker = async () => {
    for (let next = queue.shift(); next !== undefined; next = queue.shift()) {
      try {
        await task(next);
      } catch {
        // The task records its own failure; the pool just moves on.
      }
    }
  };
  await Promise.all(Array.from({ length: Math.min(limit, queue.length) }, worker));
}
