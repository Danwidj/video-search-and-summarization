// SPDX-License-Identifier: Apache-2.0

/**
 * A batch upload: several files queued on the upload page and run strictly one
 * after another, each through the same upload, conversion and analysis as a
 * single upload, so each file becomes its own video and report. Everything
 * here is pure, so the queue's order, failure isolation, removal and
 * cancellation are tested without a browser (tests/batch-upload.test.mjs);
 * hooks/use-batch-upload.ts wires it to React and the console's routes.
 */

/** The steps a file runs through, in order. */
export const BATCH_STAGES = ['uploading', 'converting', 'analysing'] as const;
export type BatchStage = (typeof BATCH_STAGES)[number];

export const batchStageLabels: Record<BatchStage, string> = {
  uploading: 'Uploading',
  converting: 'Converting',
  analysing: 'Analysing',
};

/** `cancelled`: the batch was cancelled before this file finished uploading, so nothing of it was stored. */
export type BatchStatus = 'queued' | BatchStage | 'done' | 'failed' | 'cancelled';

export interface BatchItem {
  /** Local key; the stored name is only known after the upload. */
  key: string;
  /** The file's own name until the upload answers, then the name it is stored under. */
  name: string;
  size: number;
  status: BatchStatus;
  /** The step that failed, for a failed file. */
  failedAt: BatchStage | null;
  /** 0 to 100 while the bytes upload. */
  uploadProgress: number;
  error: string | null;
  /** Whether the console converted the file to H.264 (null until the upload answers). */
  converted: boolean | null;
  /** The new report, once the analysis has stored it. */
  report: { videoId: string; revisionId: number } | null;
}

export interface BatchDeps {
  /**
   * Uploads (and, on the server, converts) one file and returns its R2 key and stored name.
   * `onUploaded` fires once every byte is sent and the server is probing or converting.
   */
  upload(
    file: File,
    onProgress: (progress: number) => void,
    onUploaded: () => void,
  ): Promise<{ filePath: string; filename: string; converted: boolean }>;
  analyse(input: { filePath: string; filename: string; model: string }): Promise<{ videoId: string; revisionId: number }>;
}

/** The message a single upload rejects with when it is cancelled (hooks/use-video-upload.ts). */
export const UPLOAD_CANCELLED_MESSAGE = 'Upload was cancelled';

/** Shown when the upload step fails with no message of its own, as when the console refuses a file that is not a video. */
export const UPLOAD_REFUSED_MESSAGE = 'The file was not accepted as a video';

/** The reason a file is refused before it is sent, by its name and type. */
export const NOT_A_VIDEO_MESSAGE = 'Not an MP4, MKV, MOV, or WebM video';

/** Whether the browser's file looks like a video the console takes; anything else fails at once without being sent. */
export const isVideoFile = (file: { name: string; type: string }): boolean =>
  file.type.startsWith('video/') || /\.(mp4|mkv|mov|webm)$/i.test(file.name);

const ACTIVE: ReadonlySet<BatchStatus> = new Set(BATCH_STAGES);

export const isActive = (item: BatchItem): boolean => ACTIVE.has(item.status);

export function newBatchItem(file: { name: string; size: number; type: string }, key: string): BatchItem {
  const item: BatchItem = {
    key,
    name: file.name,
    size: file.size,
    status: 'queued',
    failedAt: null,
    uploadProgress: 0,
    error: null,
    converted: null,
    report: null,
  };
  return isVideoFile(file) ? item : { ...item, status: 'failed', failedAt: 'uploading', error: NOT_A_VIDEO_MESSAGE };
}

/**
 * The file to start next: the first queued one, and only when no file is
 * running, so the batch is strictly one at a time and in the order added.
 */
export function nextToRun(items: readonly BatchItem[]): string | null {
  if (items.some(isActive)) return null;
  return items.find((item) => item.status === 'queued')?.key ?? null;
}

/** Removes a file that has not started; a running or finished file stays. */
export function removeQueued(items: readonly BatchItem[], key: string): BatchItem[] {
  return items.filter((item) => item.key !== key || item.status !== 'queued');
}

/**
 * Cancels the batch: every queued file is cancelled. The running file is only
 * cancelled while its bytes upload (the caller aborts it); once the console is
 * converting or the agent analysing, it finishes, as a single upload does.
 */
export function cancelQueued(items: readonly BatchItem[]): BatchItem[] {
  return items.map((item) => (item.status === 'queued' ? { ...item, status: 'cancelled' } : item));
}

/** Whether cancelling now should abort the running file: only while its bytes are still uploading. */
export const shouldAbortRunning = (items: readonly BatchItem[]): boolean => items.some((item) => item.status === 'uploading');

const failureMessage = (error: unknown, fallback: string): string =>
  error instanceof Error && error.message.trim() ? error.message : fallback;

/**
 * Runs one file through Uploading, Converting and Analysing, reporting each
 * change through `update`. It never throws: a failure is recorded on the item
 * at the step that failed, so the next file starts as usual.
 */
export async function runBatchItem(
  file: File,
  model: string,
  deps: BatchDeps,
  update: (change: Partial<BatchItem>) => void,
): Promise<void> {
  let stage: BatchStage = 'uploading';
  try {
    update({ status: stage, uploadProgress: 0, error: null, failedAt: null });
    const uploaded = await deps.upload(
      file,
      (uploadProgress) => update({ uploadProgress }),
      () => {
        stage = 'converting';
        update({ status: stage, uploadProgress: 100 });
      },
    );
    stage = 'analysing';
    update({ status: stage, name: uploaded.filename, converted: uploaded.converted });
    const report = await deps.analyse({ filePath: uploaded.filePath, filename: uploaded.filename, model });
    update({ status: 'done', report });
  } catch (error) {
    if (stage !== 'analysing' && error instanceof Error && error.message === UPLOAD_CANCELLED_MESSAGE) {
      update({ status: 'cancelled', error: null });
      return;
    }
    const fallback = stage === 'analysing' ? 'The analysis failed' : UPLOAD_REFUSED_MESSAGE;
    update({ status: 'failed', failedAt: stage, error: failureMessage(error, fallback) });
  }
}

/**
 * Runs the queue until no file is left to start: `current` reads the latest
 * items (files may be added, removed or cancelled meanwhile) and `run` takes
 * one file to the end. One failing file never stops the ones after it.
 */
export async function drainQueue(current: () => readonly BatchItem[], run: (key: string) => Promise<void>): Promise<void> {
  for (let key = nextToRun(current()); key !== null; key = nextToRun(current())) {
    try {
      await run(key);
    } catch {
      // runBatchItem records its own failure; the queue just moves on.
    }
  }
}

/** 0 to 100 for one file: the upload fills the first third as it goes, then a third per step. */
export function itemProgress(item: BatchItem): number {
  if (item.status === 'done') return 100;
  if (item.status === 'queued' || item.status === 'cancelled') return 0;
  const stage = item.status === 'failed' ? (item.failedAt ?? 'uploading') : item.status;
  const index = BATCH_STAGES.indexOf(stage);
  const within = stage === 'uploading' ? item.uploadProgress / 100 : 0.5;
  return Math.max(2, Math.round(((index + within) / BATCH_STAGES.length) * 100));
}

export interface BatchSummary {
  total: number;
  done: number;
  failed: number;
  cancelled: number;
  /** Files still queued or running. */
  pending: number;
  /** Percent of the batch done: each file's own progress averaged, a failed or cancelled file counted as finished. */
  percent: number;
  /** No file is queued or running. */
  settled: boolean;
}

export function summariseBatch(items: readonly BatchItem[]): BatchSummary {
  const count = (status: BatchStatus) => items.filter((item) => item.status === status).length;
  const done = count('done');
  const failed = count('failed');
  const cancelled = count('cancelled');
  const pending = items.length - done - failed - cancelled;
  const finished = (item: BatchItem) => item.status === 'failed' || item.status === 'cancelled';
  return {
    total: items.length,
    done,
    failed,
    cancelled,
    pending,
    percent: items.length
      ? Math.round(items.reduce((sum, item) => sum + (finished(item) ? 100 : itemProgress(item)), 0) / items.length)
      : 0,
    settled: items.length > 0 && pending === 0,
  };
}
