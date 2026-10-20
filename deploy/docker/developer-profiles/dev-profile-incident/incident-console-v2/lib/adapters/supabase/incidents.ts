// SPDX-License-Identifier: Apache-2.0

import {
  reviewFromRow, reviewTransitionFromRpc, runReportFromRows, structuredEditResultFromRpc,
} from '@/lib/adapters/supabase/mappers/report';
import { reportListFromRpc, reportListRpcArgs } from '@/lib/adapters/supabase/mappers/report-library';
import type {
  IncidentRepository, ReportList, ReportListQuery, ReviewState, ReviewTransition, RunKey, RunReportRecord, StructuredEditResult,
} from '@/lib/ports';
import type { PostgrestClient } from '@/lib/postgrest/client';
import type { StructuredEdit } from '@/lib/reports/edit-draft';
import type { ReviewStatus } from '@/lib/reports/storage';

const runFilter = (key: RunKey) => ({ incident_id: key.videoId, model_run_id: key.modelRunId });

export class SupabaseIncidentAdapter implements IncidentRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async listReports(query: ReportListQuery): Promise<ReportList> {
    return reportListFromRpc(await this.db.rpc('list_incident_report_summaries', reportListRpcArgs(query)));
  }

  // The effective_* views hold the reviewer's version of a run when it has one, else the AI's,
  // with the AI tables' columns, so the row mapping is the same for both.
  async getRunReport(key: RunKey): Promise<RunReportRecord | null> {
    const filter = runFilter(key);
    const [modelRun, video, review, incident, entities, instruments, assets, reportRow] = await Promise.all([
      this.db.selectOne('model_runs', { id: key.modelRunId }),
      this.db.selectOne('videos', { id: key.videoId }),
      this.db.selectOne('review_status', filter),
      this.db.selectOne('effective_incidents', filter),
      this.db.selectMany('effective_entities', { filters: filter }),
      this.db.selectMany('effective_instruments', { filters: filter }),
      this.db.selectMany('effective_assets', { filters: filter }),
      this.db.selectOne('reports', filter),
    ]);
    if (!modelRun || !video || !incident) return null;
    return runReportFromRows({ ...key, video, modelRun, incident, entities, instruments, assets, review, reportRow });
  }

  async runExists(key: RunKey): Promise<boolean> {
    return Boolean(await this.db.selectOne('incidents', runFilter(key), 'incident_id'));
  }

  async getReview(key: RunKey): Promise<ReviewState | null> {
    return reviewFromRow(await this.db.selectOne('review_status', runFilter(key)));
  }

  async setReviewStatus(key: RunKey, status: ReviewStatus, reviewer: string): Promise<ReviewTransition> {
    return reviewTransitionFromRpc(await this.db.rpc('set_review_status', {
      p_incident_id: key.videoId,
      p_model_run_id: key.modelRunId,
      p_status: status,
      p_reviewer: reviewer,
    }), status);
  }

  // save_human_report_edit, not the apply_structured_report_edit shim kept for older consoles, so
  // the shim can be dropped without another console change.
  async applyStructuredEdit(key: RunKey, edit: StructuredEdit, editedBy: string): Promise<StructuredEditResult> {
    const result = await this.db.rpc('save_human_report_edit', {
      p_incident_id: key.videoId,
      p_model_run_id: key.modelRunId,
      p_edit: edit,
      p_edited_by: editedBy,
    });
    return structuredEditResultFromRpc(result, key, edit, editedBy);
  }

  async deleteRun(key: RunKey): Promise<void> {
    await this.db.deleteWhere('incidents', runFilter(key));
  }
}
