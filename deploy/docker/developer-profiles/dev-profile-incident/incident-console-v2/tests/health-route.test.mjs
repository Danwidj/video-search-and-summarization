// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, beforeEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { GET } = await import('../app/api/health/route.ts');

const originalEnv = { ...process.env };
const originalFetch = globalThis.fetch;

function setHealthyEnv() {
  process.env.INCIDENT_AGENT_BASE_URL = 'http://agent.test:8000';
  process.env.VLM_GATEWAY_URL = 'http://gateway.test:8600';
  process.env.INCIDENT_SUPABASE_URL = 'https://supabase.test';
  process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY = 'test-key';
  process.env.R2_ACCOUNT_ID = 'test-account';
  process.env.R2_ACCESS_KEY = 'test-access-key';
  process.env.R2_SECRET_KEY = 'test-secret-key';
  process.env.R2_BUCKET = 'test-bucket';
}

beforeEach(() => {
  setHealthyEnv();
});

afterEach(() => {
  for (const key of Object.keys(process.env)) {
    if (!(key in originalEnv)) {
      delete process.env[key];
    } else {
      process.env[key] = originalEnv[key];
    }
  }
  globalThis.fetch = originalFetch;
});

test('gateway mode: ready when all services are healthy', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  globalThis.fetch = async (url) => {
    return { ok: true, status: 200 };
  };

  const response = await GET();
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.status, 'ready');
  assert.equal(payload.services.agent.reachable, true);
  assert.equal(payload.services.gateway.reachable, true);
  assert.equal(payload.services.postgrest.reachable, true);
  assert.equal(payload.services.r2.configured, true);
});

test('gateway mode: degraded when gateway is unreachable', async () => {
  process.env.ANALYSIS_MODE = 'gateway';
  globalThis.fetch = async (url) => {
    const urlStr = String(url);
    if (urlStr.includes('8600')) {
      return { ok: false, status: 503 };
    }
    return { ok: true, status: 200 };
  };

  const response = await GET();
  assert.equal(response.status, 503);
  const payload = await response.json();
  assert.equal(payload.status, 'degraded');
  assert.equal(payload.services.gateway.reachable, false);
});

test('agent mode: ready even when gateway is unreachable', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  globalThis.fetch = async (url) => {
    const urlStr = String(url);
    if (urlStr.includes('8600')) {
      return { ok: false, status: 503 };
    }
    return { ok: true, status: 200 };
  };

  const response = await GET();
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.status, 'ready');
  assert.equal(payload.services.gateway.reachable, false);
  assert.equal(payload.services.agent.reachable, true);
  assert.equal(payload.services.postgrest.reachable, true);
  assert.equal(payload.services.r2.configured, true);
});

test('agent mode: ready when gateway is unconfigured', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  delete process.env.VLM_GATEWAY_URL;

  globalThis.fetch = async () => ({ ok: true, status: 200 });

  const response = await GET();
  assert.equal(response.status, 200);
  const payload = await response.json();
  assert.equal(payload.status, 'ready');
  assert.equal(payload.services.gateway.configured, false);
  assert.equal(payload.services.gateway.reachable, false);
});

test('agent mode: degraded when agent is unreachable', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  globalThis.fetch = async (url) => {
    const urlStr = String(url);
    if (urlStr.includes('8000')) {
      return { ok: false, status: 503 };
    }
    return { ok: true, status: 200 };
  };

  const response = await GET();
  assert.equal(response.status, 503);
  const payload = await response.json();
  assert.equal(payload.status, 'degraded');
  assert.equal(payload.services.agent.reachable, false);
});

test('agent mode: degraded when PostgREST is unreachable', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  globalThis.fetch = async (url) => {
    const urlStr = String(url);
    if (urlStr.includes('supabase')) {
      return { ok: false, status: 503 };
    }
    return { ok: true, status: 200 };
  };

  const response = await GET();
  assert.equal(response.status, 503);
  const payload = await response.json();
  assert.equal(payload.status, 'degraded');
  assert.equal(payload.services.postgrest.reachable, false);
});

test('agent mode: degraded when R2 is unconfigured', async () => {
  process.env.ANALYSIS_MODE = 'agent';
  delete process.env.R2_BUCKET;

  globalThis.fetch = async () => ({ ok: true, status: 200 });

  const response = await GET();
  assert.equal(response.status, 503);
  const payload = await response.json();
  assert.equal(payload.status, 'degraded');
  assert.equal(payload.services.r2.configured, false);
});
