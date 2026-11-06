// SPDX-License-Identifier: Apache-2.0

// How long an analysis may run: the console's 600 s agent-mode limit (INCIDENT_ANALYSIS_TIMEOUT_SECONDS), the gateway
// keeping each model's own timeout, the plain message when the limit passes, HttpIncidentAgent holding the connection
// open with no header timeout of its own, and the job loop not treating a long run as stale.

import assert from 'node:assert/strict';
import http from 'node:http';
import { register } from 'node:module';
import { afterEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

await import('../src/modules/contract/infrastructure/loader.ts');

const { DEFAULT_AGENT_ANALYSIS_TIMEOUT_SECONDS, runContractAnalysis, AnalysisRequestError } = await import(
  '../src/modules/analysis/application/run-contract-analysis.ts'
);
const { AgentRequestError } = await import('../src/modules/analysis/domain/IncidentAgent.ts');
const { getContractCatalog } = await import('../src/modules/contract/domain/ContractCatalog.ts');
const { HttpIncidentAgent } = await import('../src/modules/analysis/infrastructure/agent/incident-agent.ts');
const { getServiceConfiguration } = await import('../src/lib/env.ts');
const jobs = await import('../src/modules/jobs/domain/job.ts');

const realTimeout = AbortSignal.timeout;
const realEnvironment = process.env.INCIDENT_ANALYSIS_TIMEOUT_SECONDS;

afterEach(() => {
  AbortSignal.timeout = realTimeout;
  if (realEnvironment === undefined) delete process.env.INCIDENT_ANALYSIS_TIMEOUT_SECONDS;
  else process.env.INCIDENT_ANALYSIS_TIMEOUT_SECONDS = realEnvironment;
});

/** Records the millisecond limit of each AbortSignal.timeout the analysis creates. */
function recordLimits() {
  const limits = [];
  AbortSignal.timeout = (ms) => {
    limits.push(ms);
    return realTimeout.call(AbortSignal, ms);
  };
  return limits;
}

function ports(overrides) {
  const failed = [];
  return {
    failed,
    ports: {
      runs: {
        recordUploadedVideo: async () => {},
        saveFailedAttempt: async (attempt) => void failed.push(attempt),
        saveRun: async () => 1,
      },
      videos: {
        verify: async () => ({ contentLength: 10 }),
        playbackUrl: async () => 'https://r2.example/clip.mp4',
        durationSeconds: async () => 20,
      },
      gateway: null,
      agent: null,
      catalog: getContractCatalog(),
      randomUUID: () => '00000000-0000-4000-8000-000000000000',
      ...overrides,
    },
  };
}

const input = () => ({ videoId: 'v1', r2Key: 'uploads/clip.mp4', model: getContractCatalog().allowedModels()[0].id });

test('an agent-mode analysis is abandoned at 600 s by default', async () => {
  const limits = recordLimits();
  const { ports: p } = ports({ agent: { analyze: async () => ({ status: 500, ok: false, statusText: 'x', text: 'x' }) } });
  await assert.rejects(runContractAnalysis(input(), p, 'agent'), AnalysisRequestError);
  assert.equal(DEFAULT_AGENT_ANALYSIS_TIMEOUT_SECONDS, 600);
  assert.deepEqual(limits, [600_000]);
});

test('agentTimeoutSeconds overrides the agent-mode limit', async () => {
  const limits = recordLimits();
  const { ports: p } = ports({
    agentTimeoutSeconds: 123,
    agent: { analyze: async () => ({ status: 500, ok: false, statusText: 'x', text: 'x' }) },
  });
  await assert.rejects(runContractAnalysis(input(), p, 'agent'), AnalysisRequestError);
  assert.deepEqual(limits, [123_000]);
});

test('INCIDENT_ANALYSIS_TIMEOUT_SECONDS is read as a positive number of seconds and nothing else', () => {
  delete process.env.INCIDENT_ANALYSIS_TIMEOUT_SECONDS;
  assert.equal(getServiceConfiguration().analysisTimeoutSeconds, undefined);
  for (const bad of ['', '0', '-5', 'abc']) {
    process.env.INCIDENT_ANALYSIS_TIMEOUT_SECONDS = bad;
    assert.equal(getServiceConfiguration().analysisTimeoutSeconds, undefined, bad);
  }
  process.env.INCIDENT_ANALYSIS_TIMEOUT_SECONDS = '900';
  assert.equal(getServiceConfiguration().analysisTimeoutSeconds, 900);
});

test('gateway mode keeps the model timeout from contracts/inference.json', async () => {
  const limits = recordLimits();
  const model = getContractCatalog().allowedModels()[0];
  const { ports: p } = ports({
    agentTimeoutSeconds: 999,
    gateway: {
      complete: async () => {
        throw new Error('stop here');
      },
    },
  });
  await assert.rejects(runContractAnalysis(input(), p, 'gateway'), /stop here/);
  assert.deepEqual(limits, [model.timeout_seconds * 1000]);
});

test('a timed-out agent call is recorded and reported plainly: the main call was still running, no report saved', async () => {
  const { ports: p, failed } = ports({
    agentTimeoutSeconds: 600,
    agent: {
      analyze: async () => {
        throw new AgentRequestError('AGENT_TIMEOUT', 'The operation was aborted due to timeout');
      },
    },
  });
  await assert.rejects(runContractAnalysis(input(), p, 'agent'), (error) => {
    assert.ok(error instanceof AnalysisRequestError);
    assert.equal(error.status, 504);
    assert.match(error.message, /did not finish within 600 s: the model's main call was still running, so no report was saved/);
    return true;
  });
  assert.equal(failed.length, 1);
  assert.equal(failed[0].failure.code, 'AGENT_TIMEOUT');
  assert.doesNotMatch(failed[0].failure.message, /operation was aborted/);
});

test('a running job that heartbeats every 15 s for 10 minutes is never stale; one that stops is stale after 180 s', () => {
  const start = new Date('2026-11-07T00:00:00Z');
  const running = (heartbeatAt) => ({ status: 'running', createdAt: start.toISOString(), startedAt: start.toISOString(), heartbeatAt });
  const iso = (seconds) => new Date(start.getTime() + seconds * 1000).toISOString();
  for (let seconds = jobs.HEARTBEAT_SECONDS; seconds <= 660; seconds += jobs.HEARTBEAT_SECONDS) {
    const lastBeat = seconds - (seconds % jobs.HEARTBEAT_SECONDS);
    assert.equal(jobs.isStale(running(iso(lastBeat)), new Date(start.getTime() + seconds * 1000)), false, `${seconds} s`);
  }
  assert.equal(jobs.isStale(running(iso(60)), new Date(start.getTime() + 241_000)), true);
  assert.ok(jobs.HEARTBEAT_SECONDS * 2 < jobs.STALE_SECONDS);
});

async function withServer(handler, run) {
  const server = http.createServer(handler);
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  try {
    await run(`http://127.0.0.1:${server.address().port}`);
  } finally {
    server.closeAllConnections();
    await new Promise((resolve) => server.close(resolve));
  }
}

const request = {
  videoId: 'v1',
  videoKey: 'k',
  videoUrl: 'u',
  modelRunId: 'm',
  model: 'x',
  additionalInstruction: null,
  videoDurationSeconds: 12,
};

test('HttpIncidentAgent posts the analysis and returns the answer, a 4xx included', async () => {
  let seen;
  await withServer(
    (req, res) => {
      let body = '';
      req.on('data', (c) => (body += c));
      req.on('end', () => {
        seen = { url: req.url, method: req.method, body: JSON.parse(body) };
        res.writeHead(422, { 'Content-Type': 'application/json' }).end('{"detail":"no"}');
      });
    },
    async (base) => {
      const answer = await new HttpIncidentAgent(`${base}/`).analyze(request, AbortSignal.timeout(5000));
      assert.deepEqual([answer.status, answer.ok, answer.text], [422, false, '{"detail":"no"}']);
      assert.equal(seen.url, '/api/v1/incidents/v1/analyze');
      assert.equal(seen.method, 'POST');
      assert.deepEqual([seen.body.video_url, seen.body.skip_rp1, seen.body.video_duration_seconds], ['u', true, 12]);
    },
  );
});

test('HttpIncidentAgent has no header timeout of its own: only the signal ends a silent call, as AGENT_TIMEOUT', async () => {
  await withServer(
    () => {}, // the agent sends nothing until it has saved the report
    async (base) => {
      const started = Date.now();
      await assert.rejects(new HttpIncidentAgent(base).analyze(request, AbortSignal.timeout(400)), (error) => {
        assert.ok(error instanceof AgentRequestError);
        assert.equal(error.code, 'AGENT_TIMEOUT');
        return true;
      });
      assert.ok(Date.now() - started >= 380);
    },
  );
});

test('HttpIncidentAgent reports an unreachable agent as AGENT_FETCH_FAILED', async () => {
  const server = http.createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  await new Promise((resolve) => server.close(resolve));
  await assert.rejects(new HttpIncidentAgent(`http://127.0.0.1:${port}`).analyze(request, AbortSignal.timeout(5000)), (error) => {
    assert.ok(error instanceof AgentRequestError);
    assert.equal(error.code, 'AGENT_FETCH_FAILED');
    return true;
  });
});
