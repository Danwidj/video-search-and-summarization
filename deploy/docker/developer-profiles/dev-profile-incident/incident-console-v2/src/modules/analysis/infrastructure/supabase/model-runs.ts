// SPDX-License-Identifier: Apache-2.0

// ModelRunRepository over PostgREST (table model_runs).

import type { PostgrestClient } from '@/lib/postgrest/client';
import type { ModelRun, ModelRunRepository } from '@/modules/analysis/domain/ModelRunRepository';

const text = (value: unknown): string | null => (typeof value === 'string' ? value : null);

export class SupabaseModelRunAdapter implements ModelRunRepository {
  private readonly db: PostgrestClient;

  constructor(db: PostgrestClient) {
    this.db = db;
  }

  async recordRun(run: ModelRun): Promise<void> {
    await this.db.upsert(
      'model_runs',
      {
        id: run.id,
        model_name: run.modelName,
        model_version: run.modelVersion,
        prompt_version: run.promptVersion,
        run_datetime: run.runAt,
        notes: run.notes,
      },
      'id',
    );
  }

  async getRun(id: string): Promise<ModelRun | null> {
    const row = await this.db.selectOne('model_runs', { id });
    if (!row) return null;
    return {
      id: String(row.id),
      modelName: String(row.model_name),
      modelVersion: text(row.model_version),
      promptVersion: text(row.prompt_version),
      runAt: String(row.run_datetime ?? ''),
      notes: text(row.notes),
    };
  }
}
