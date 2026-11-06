// SPDX-License-Identifier: Apache-2.0

// AnalysisJobRepository over PostgREST: the analysis_jobs table and its
// functions (supabase/migrations/20261031120000_analysis_jobs.sql). Every state change
// is a function, so it runs on the database clock and is atomic.

import type { PostgrestClient } from '@/lib/postgrest/client';
import { DuplicateUploadError, isMissingHashColumn, isUniqueViolation } from '@/modules/uploads/domain/duplicate';
import type { AnalysisJobRepository, NewAnalysisJob } from '@/modules/jobs/domain/AnalysisJobRepository';
import { type AnalysisJob, JOB_STATUSES, type JobOutcome, type JobStatus, jobsList } from '@/modules/jobs/domain/job';

const text = (value: unknown): string | null => (typeof value === 'string' ? value : null);
const integer = (value: unknown): number | null => (value === null || value === undefined ? null : Number(value));

export function jobFromRow(row: Record<string, unknown>): AnalysisJob {
  const status = String(row.status);
  if (!JOB_STATUSES.includes(status as JobStatus)) throw new Error(`analysis_jobs row ${String(row.id)} has an unknown status ${status}`);
  return {
    id: Number(row.id),
    filePath: String(row.file_path ?? ''),
    filename: String(row.filename ?? ''),
    model: text(row.model),
    status: status as JobStatus,
    attempts: Number(row.attempts ?? 0),
    error: text(row.error),
    createdAt: String(row.created_at ?? ''),
    startedAt: text(row.started_at),
    finishedAt: text(row.finished_at),
    heartbeatAt: text(row.heartbeat_at),
    videoId: text(row.video_id),
    revisionId: integer(row.revision_id),
    contentSha256: text(row.content_sha256)?.trim() || null,
  };
}

/** A SETOF function answers with a list; zero rows means the condition did not hold. */
function firstJob(result: unknown): AnalysisJob | null {
  const rows = Array.isArray(result) ? result : result ? [result] : [];
  return rows.length ? jobFromRow(rows[0] as Record<string, unknown>) : null;
}

export class SupabaseAnalysisJobAdapter implements AnalysisJobRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async findActiveByContentHash(contentSha256: string): Promise<AnalysisJob | null> {
    try {
      const rows = await this.db.selectWhere('analysis_jobs', {
        select: '*',
        content_sha256: `eq.${contentSha256}`,
        status: 'in.(queued,running)',
        limit: '1',
      });
      return rows.length ? jobFromRow(rows[0]) : null;
    } catch (error) {
      if (isMissingHashColumn(error)) return null;
      throw error;
    }
  }

  async enqueue(job: NewAnalysisJob): Promise<AnalysisJob> {
    const row = { file_path: job.filePath, filename: job.filename, model: job.model };
    if (!job.contentSha256) return jobFromRow(await this.db.insertRow('analysis_jobs', row));
    try {
      return jobFromRow(await this.db.insertRow('analysis_jobs', { ...row, content_sha256: job.contentSha256 }));
    } catch (error) {
      // Before the migration the column does not exist: queue without it, as the console did before.
      if (isMissingHashColumn(error)) return jobFromRow(await this.db.insertRow('analysis_jobs', row));
      if (!isUniqueViolation(error)) throw error;
      // The database's unique index on queued and running jobs decided the race: report the winner.
      const active = await this.findActiveByContentHash(job.contentSha256);
      if (!active) throw error;
      throw new DuplicateUploadError({ kind: 'job', name: active.filename, videoId: null, jobId: active.id });
    }
  }

  async list(recent: number): Promise<AnalysisJob[]> {
    const [active, finished] = await Promise.all([
      this.db.selectWhere('analysis_jobs', { select: '*', status: 'in.(queued,running)', order: 'created_at.asc,id.asc' }),
      this.db.selectWhere('analysis_jobs', {
        select: '*',
        status: 'in.(done,failed,cancelled)',
        order: 'created_at.desc,id.desc',
        limit: String(recent),
      }),
    ]);
    return jobsList([...active, ...finished].map(jobFromRow), recent);
  }

  async claim(staleSeconds: number): Promise<AnalysisJob | null> {
    return firstJob(await this.db.rpc('claim_analysis_job', { p_stale_seconds: staleSeconds }));
  }

  async heartbeat(id: number, attempt: number): Promise<boolean> {
    return (await this.db.rpc('touch_analysis_job', { p_id: id, p_attempt: attempt })) === true;
  }

  async finish(id: number, attempt: number, outcome: JobOutcome): Promise<AnalysisJob | null> {
    const done = outcome.status === 'done';
    return firstJob(
      await this.db.rpc('finish_analysis_job', {
        p_id: id,
        p_attempt: attempt,
        p_status: outcome.status,
        p_error: done ? null : outcome.error,
        p_video_id: done ? outcome.videoId : null,
        p_revision_id: done ? outcome.revisionId : null,
      }),
    );
  }

  async retry(id: number): Promise<AnalysisJob | null> {
    return firstJob(await this.db.rpc('retry_analysis_job', { p_id: id }));
  }

  async cancel(id: number): Promise<AnalysisJob | null> {
    return firstJob(await this.db.rpc('cancel_analysis_job', { p_id: id }));
  }
}
