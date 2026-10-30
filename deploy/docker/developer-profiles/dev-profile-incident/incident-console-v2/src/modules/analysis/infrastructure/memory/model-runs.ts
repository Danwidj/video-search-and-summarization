// SPDX-License-Identifier: Apache-2.0

// In-memory ModelRunRepository for tests: same guarantees as the Supabase adapter.

import type { ModelRun, ModelRunRepository } from '@/modules/analysis/domain/ModelRunRepository';

export class InMemoryModelRunRepository implements ModelRunRepository {
  readonly runs = new Map<string, ModelRun>();

  async recordRun(run: ModelRun): Promise<void> {
    this.runs.set(run.id, { ...run });
  }

  async getRun(id: string): Promise<ModelRun | null> {
    const run = this.runs.get(id);
    return run ? { ...run } : null;
  }
}
