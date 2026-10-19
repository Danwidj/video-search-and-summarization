// SPDX-License-Identifier: Apache-2.0

import { reviewFromRow, reviewToRow, runReportFromRows } from '@/lib/adapters/supabase/mappers/report';
import { reportListFromRpc, reportListRpcArgs } from '@/lib/adapters/supabase/mappers/report-library';
import type {
  IncidentRepository, ReportList, ReportListQuery, ReviewState, RunKey, RunReportRecord, StructuredEditResult,
} from '@/lib/ports';
import type { PostgrestClient } from '@/lib/postgrest/client';
import type { StructuredEdit } from '@/lib/reports/edit-draft';

type Row = Record<string, unknown>;

const text = (value: unknown): string | null => (typeof value === 'string' ? value : null);
const runFilter = (key: RunKey) => ({ incident_id: key.videoId, model_run_id: key.modelRunId });
const asRow = (value: unknown): Row => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : {});

export class SupabaseIncidentAdapter implements IncidentRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async listReports(query: ReportListQuery): Promise<ReportList> {
    return reportListFromRpc(await this.db.rpc('list_incident_report_summaries', reportListRpcArgs(query)));
  }

  async getRunReport(key: RunKey): Promise<RunReportRecord | null> {
    const filter = runFilter(key);
    const [modelRun, video, review, incident, entities, instruments, assets, reportRow] = await Promise.all([
      this.db.selectOne('model_runs', { id: key.modelRunId }),
      this.db.selectOne('videos', { id: key.videoId }),
      this.db.selectOne('review_status', filter),
      this.db.selectOne('incidents', filter),
      this.db.selectMany('entities', { filters: filter }),
      this.db.selectMany('instruments', { filters: filter }),
      this.db.selectMany('assets', { filters: filter }),
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

  async saveReview(key: RunKey, review: ReviewState): Promise<void> {
    await this.db.upsert('review_status', reviewToRow(key, review), 'incident_id,model_run_id');
  }

  async applyStructuredEdit(key: RunKey, edit: StructuredEdit, editedBy: string): Promise<StructuredEditResult> {
    const result = asRow(await this.db.rpc('apply_structured_report_edit', {
      p_incident_id: key.videoId,
      p_model_run_id: key.modelRunId,
      p_edit: edit,
      p_edited_by: editedBy,
    }));
    // The RPC returns exactly these keys, with duration = end - start (20260927160000_apply_structured_report_edit.sql).
    return {
      incidentId: text(result.incidentId) ?? key.videoId,
      modelRunId: text(result.modelRunId) ?? key.modelRunId,
      editedBy: text(result.editedBy) ?? editedBy.trim(),
      editedAt: text(result.editedAt) ?? '',
      duration: typeof result.duration === 'number' ? result.duration : edit.incident.end_timestamp - edit.incident.start_timestamp,
    };
  }

  async deleteRun(key: RunKey): Promise<void> {
    await this.db.deleteWhere('incidents', runFilter(key));
  }
}
