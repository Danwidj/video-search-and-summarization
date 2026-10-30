// SPDX-License-Identifier: Apache-2.0

/**
 * The four stages every file of a batch passes through, in order. Matches are checked before any
 * report is built, so the reviewer decides the suggestions first and each incident gets one report.
 */
export const BATCH_STAGES = ['upload', 'analyse', 'matches', 'report'] as const;
export type BatchStage = (typeof BATCH_STAGES)[number];

export const batchStageLabels: Record<BatchStage, string> = {
  upload: 'Upload',
  analyse: 'Analyse',
  matches: 'Check matches',
  report: 'Build report',
};

/**
 * `waiting`: analysed, held until every file of the batch is analysed or failed so matches compare the whole batch.
 * `deciding`: matches checked, report not built because a suggestion on its incident is undecided; the Matches tab and report banner build it after the decision.
 */
export type BatchStatus = 'queued' | 'running' | 'waiting' | 'deciding' | 'failed' | 'done';

export interface BatchItem {
  /** Local key; the stored name is only known after the upload. */
  key: string;
  name: string;
  size: number;
  status: BatchStatus;
  /** The stage running now, the next one when waiting, or the one that failed. */
  stage: BatchStage;
  /** 0 to 100 while the upload runs. */
  uploadProgress: number;
  error: string | null;
  /** What earlier stages produced, kept so a retry resumes where the file stopped. The incident id follows accepted merges. */
  uploaded: { sensorId: string; filePath: string; filename: string } | null;
  analysed: { incidentId: number } | null;
  /** Matches have been checked for this file. */
  checked: boolean;
  built: boolean;
  /** Suggested matches left for the reviewer; null until the check ends. */
  matches: number | null;
  /** The incident this file was joined into automatically, with the score; null when it was not. */
  autoJoined: { incidentId: number; score: number } | null;
}

/** What the check found: the matches left to decide, and the join the rule made by itself, if any. */
export interface BatchCheckResult {
  suggestions: number;
  joined: { keptIncidentId: number; mergedIncidentId: number; score: number } | null;
}

export interface BatchDeps {
  upload(file: File, onProgress: (progress: number) => void): Promise<{ sensorId: string; filePath: string; filename: string }>;
  /** Finishes the upload on the agent. */
  complete(uploaded: { sensorId: string; filename: string }): Promise<void>;
  analyse(input: { uploaded: { sensorId: string; filePath: string; filename: string }; model: string }): Promise<{ incidentId: number }>;
  build(incidentId: number): Promise<void>;
  evaluate(incidentId: number): Promise<BatchCheckResult>;
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
    checked: false,
    built: false,
    matches: null,
    autoJoined: null,
  };
}

/** 0 to 100 for one file: each stage is worth a quarter, the upload fills its share as it goes. */
export function itemProgress(item: BatchItem): number {
  if (item.status === 'done') return 100;
  if (item.status === 'queued') return 0;
  const index = BATCH_STAGES.indexOf(item.stage);
  const within = item.stage === 'upload' && item.status === 'running' ? item.uploadProgress / 100 : item.status === 'running' ? 0.5 : 0;
  return Math.max(2, Math.round(((index + (item.status === 'failed' ? 0.5 : within)) / BATCH_STAGES.length) * 100));
}

export interface BatchSummary {
  total: number;
  done: number;
  failed: number;
  /** Files whose report waits for a decision on a suggested match; they are handed to the reviewer, so the batch can settle. */
  deciding: number;
  /** Files still queued, running or waiting for the rest of the batch. */
  running: number;
  /** Files whose upload is in flight; only these can be cancelled. */
  uploading: number;
  /** Percent of the batch's work done: each file's own progress averaged, a file awaiting a decision counted as finished. */
  percent: number;
  settled: boolean;
}

export function summariseBatch(items: BatchItem[]): BatchSummary {
  const count = (status: BatchStatus) => items.filter((item) => item.status === status).length;
  const done = count('done');
  const failed = count('failed');
  const deciding = count('deciding');
  const running = items.length - done - failed - deciding;
  return {
    total: items.length,
    done,
    failed,
    deciding,
    running,
    uploading: items.filter((item) => item.status === 'running' && item.stage === 'upload').length,
    percent: items.length
      ? Math.round(items.reduce((sum, item) => sum + (item.status === 'deciding' ? 100 : itemProgress(item)), 0) / items.length)
      : 0,
    settled: items.length > 0 && running === 0,
  };
}

/** Where the batch's final button leads: the Matches tab while a suggested match awaits a decision, the library otherwise. */
export const libraryHref = (summary: Pick<BatchSummary, 'deciding'>): string =>
  summary.deciding > 0 ? '/library?tab=matches' : '/library';

/** Whole seconds as m:ss for the step that is running. */
export function formatElapsed(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
}

const failureMessage = (error: unknown): string => (error instanceof Error && error.message ? error.message : 'The step failed');

/** Whether an analysis refusal means the upload's video row already exists (an earlier attempt got that far). */
export const isAlreadyStored = (error: unknown): boolean => /already exists/i.test(failureMessage(error));

/**
 * Runs one file through Upload and Analyse, reporting each change through `update`, then leaves it
 * `waiting` for the rest of the batch. It never throws: a failure is recorded on the item at the stage
 * that failed, so a sibling file is unaffected and a retry resumes from that stage.
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
  let stage: BatchStage = item.uploaded ? 'analyse' : 'upload';
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
    set({ status: 'waiting', stage: 'matches' });
  } catch (error) {
    update({ status: 'failed', stage, error: failureMessage(error) });
  }
}

/**
 * After an automatic join the merged incident no longer exists: every file that pointed at it now belongs
 * to the kept one. The files joined into it keep their own note, and the one that carried the new video
 * says where it went; files already in the kept incident are unchanged.
 */
export function followJoin(items: BatchItem[], joined: NonNullable<BatchCheckResult['joined']>): BatchItem[] {
  return items.map((item) =>
    item.analysed?.incidentId === joined.mergedIncidentId
      ? { ...item, analysed: { incidentId: joined.keptIncidentId }, autoJoined: { incidentId: joined.keptIncidentId, score: joined.score } }
      : item,
  );
}

/**
 * Checks one analysed file against every other incident, including the other files of the batch, and
 * leaves it `deciding`. Never throws: a failure is recorded at the matches stage and a retry repeats only the check.
 */
export async function checkBatchItem(start: BatchItem, deps: BatchDeps, update: (change: Partial<BatchItem>) => void): Promise<void> {
  try {
    update({ status: 'running', stage: 'matches', error: null });
    const { suggestions, joined } = await deps.evaluate((start.analysed as NonNullable<BatchItem['analysed']>).incidentId);
    update({
      status: 'deciding',
      stage: 'report',
      checked: true,
      matches: suggestions,
      ...(joined ? { autoJoined: { incidentId: joined.keptIncidentId, score: joined.score } } : {}),
    });
  } catch (error) {
    update({ status: 'failed', stage: 'matches', error: failureMessage(error) });
  }
}

/**
 * Builds one incident's report once and marks every file that belongs to it done. Never throws: a
 * failure is recorded at the report stage on each of those files and a retry repeats only the build.
 */
export async function buildBatchIncident(
  incidentId: number,
  keys: string[],
  deps: Pick<BatchDeps, 'build'>,
  update: (key: string, change: Partial<BatchItem>) => void,
): Promise<void> {
  try {
    for (const key of keys) update(key, { status: 'running', stage: 'report', error: null });
    await deps.build(incidentId);
    for (const key of keys) update(key, { status: 'done', stage: 'report', built: true });
  } catch (error) {
    for (const key of keys) update(key, { status: 'failed', stage: 'report', error: failureMessage(error) });
  }
}

/** What a failed file does next: the state its retry starts from. A file with nothing analysed uploads or analyses again. */
export function retryChange(item: BatchItem): Partial<BatchItem> {
  if (!item.analysed) return { status: 'queued', error: null, stage: item.uploaded ? 'analyse' : 'upload' };
  if (!item.checked) return { status: 'waiting', error: null, stage: 'matches' };
  return { status: 'deciding', error: null, stage: 'report' };
}

export interface BatchPlan {
  /** Keys of the analysed files to check matches for now. */
  check: string[];
  /** One build per incident, with the files that belong to it. */
  build: { incidentId: number; keys: string[] }[];
}

/**
 * What the batch does next. Matches are checked only once no file is still uploading or analysing, so
 * the batch is compared as a whole. A report is built only when no file is still waiting to be checked,
 * `pendingIncidentIds` is known and no undecided suggestion names the file's incident. A file with a pending
 * suggestion stays `deciding`: the reviewer decides in the library's Matches tab or on the report page, which build the report.
 */
export function planBatch(items: BatchItem[], pendingIncidentIds: ReadonlySet<number> | null): BatchPlan {
  const early = items.some(
    (item) => (item.status === 'queued' || item.status === 'running') && (item.stage === 'upload' || item.stage === 'analyse'),
  );
  const waiting = items.filter((item) => item.status === 'waiting');
  const checking = items.some((item) => item.status === 'running' && item.stage === 'matches');
  const check = early ? [] : waiting.map((item) => item.key);
  const build = new Map<number, string[]>();
  if (waiting.length === 0 && !checking && pendingIncidentIds) {
    for (const item of items) {
      if (item.status !== 'deciding' || !item.analysed) continue;
      const { incidentId } = item.analysed;
      if (pendingIncidentIds.has(incidentId)) continue;
      build.set(incidentId, [...(build.get(incidentId) ?? []), item.key]);
    }
  }
  return { check, build: [...build].map(([incidentId, keys]) => ({ incidentId, keys })) };
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
