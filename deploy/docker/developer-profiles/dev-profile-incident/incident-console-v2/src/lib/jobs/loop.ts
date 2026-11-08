// SPDX-License-Identifier: Apache-2.0

// The background analysis loop: runs inside the console's Node process,
// started once by src/instrumentation.ts. Every POLL_MS it runs one tick
// (modules/jobs/application runNextJob): claim the oldest queued job, analyse
// it with the same code as POST /api/analysis, store done or failed. A job queued
// One job at
// a time per console, like the batch upload, which keeps within the model
// provider's rate limits. It is not a request, so no route maxDuration applies;
// the analysis limit still bounds one: 600 s in agent mode (INCIDENT_ANALYSIS_TIMEOUT_SECONDS), each model's own
// timeout (contracts/inference.json) in gateway mode. The heartbeat runs on its own timer, so a long run is not stale.
// ANALYSIS_JOB_LOOP=off leaves it stopped (jobs then wait for another console).

import { getAnalysisJobs, getDbAdapters, getUploadAnalysis } from '@/lib/container';
import { getServiceConfiguration, isR2Configured, isSupabaseConfigured, requireAnalysisConfiguration } from '@/lib/env';
import { createSearchableRepair, REPAIR_INTERVAL_MS } from '@/lib/jobs/repair';
import { readStoredJson } from '@/lib/r2/stored-json';
import { fetchEvidenceItemEmbeddings, fetchSummaryEmbedding } from '@/modules/reports/infrastructure/agent/evidence-embeddings';
import { analyseUpload } from '@/modules/analysis/application/analyse-upload';
import { jobVideoId, runNextJob } from '@/modules/jobs/application';

export const POLL_MS = 3000;

// One loop per process: Next's dev server can evaluate the instrumentation hook
// again (and modules are re-instantiated on reload), so the guard lives on
// globalThis. The atomic claim makes a second loop harmless anyway.
const STARTED = Symbol.for('incident-console-v2.analysis-job-loop');
type LoopGlobal = typeof globalThis & { [STARTED]?: boolean };

const log = (message: string) => console.warn(`[analysis jobs] ${message}`);

/** One tick; true when a job ran, so the loop takes the next one without waiting. */
export async function tick(): Promise<boolean> {
  const config = getServiceConfiguration();
  if (!isSupabaseConfigured(config)) return false;
  const finished = await runNextJob({
    jobs: getAnalysisJobs(config),
    analyse: (job) => {
      const deps = getUploadAnalysis(requireAnalysisConfiguration(config));
      return analyseUpload(
        {
          r2Key: job.filePath,
          model: job.model,
          videoId: jobVideoId(job),
          contentSha256: job.contentSha256,
        },
        deps,
      );
    },
    every: (ms, fn) => {
      const timer = setInterval(fn, ms);
      return () => clearInterval(timer);
    },
    warn: log,
  });
  if (finished) log(`job ${finished.id} (${finished.filename}) ${finished.status}${finished.error ? `: ${finished.error}` : ''}`);
  return finished !== null;
}

/**
 * The repair of searchable versions (lib/jobs/repair.ts): once at start, every REPAIR_INTERVAL_MS, and after each job.
 * Never awaited by the job loop, so it cannot delay or fail a job. Skipped while the database or the agent is not configured.
 */
export const repairSearchable = createSearchableRepair({
  log,
  deps: () => {
    const config = getServiceConfiguration();
    if (!isSupabaseConfigured(config) || !config.agentUrl) return null;
    return {
      db: getDbAdapters(config),
      embedCrops: (items) => fetchEvidenceItemEmbeddings(config, items),
      embedSummary: (summary) => fetchSummaryEmbedding(config, summary),
      readTrack: isR2Configured(config) ? readStoredJson(config) : undefined,
    };
  },
});

export function startAnalysisJobLoop(): void {
  const scope = globalThis as LoopGlobal;
  if (scope[STARTED] || process.env.ANALYSIS_JOB_LOOP?.trim().toLowerCase() === 'off') return;
  scope[STARTED] = true;
  log(
    `loop started: one job at a time, polling every ${POLL_MS / 1000} s; repairing searchable versions every ${REPAIR_INTERVAL_MS / 1000} s`,
  );
  void repairSearchable();
  setInterval(() => void repairSearchable(), REPAIR_INTERVAL_MS).unref();
  let lastError = '';
  const run = async () => {
    let busy = false;
    try {
      busy = await tick();
      lastError = '';
      if (busy) void repairSearchable();
    } catch (error) {
      // The queue is unreachable (PostgREST down, table not migrated): say so once, keep polling.
      const message = error instanceof Error ? error.message : String(error);
      if (message !== lastError) log(`cannot reach the job queue: ${message}`);
      lastError = message;
    }
    setTimeout(run, busy ? 0 : POLL_MS);
  };
  setTimeout(run, POLL_MS);
}
