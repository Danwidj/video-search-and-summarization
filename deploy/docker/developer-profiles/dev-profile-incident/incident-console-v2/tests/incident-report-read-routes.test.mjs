// SPDX-License-Identifier: Apache-2.0

// GET /api/reports/[incidentId] (one version with its coverage verdict and camera), .../revisions (the versions),
// .../frame and .../evidence-image (through the covering video), over the fake PostgREST.

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send() {
        return Promise.resolve({});
      }
    },
    GetObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
    PutObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
    HeadObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
    DeleteObjectCommand: class {
      constructor(input) {
        this.input = input;
      }
    },
  },
});
mock.module('@aws-sdk/s3-request-presigner', {
  namedExports: { getSignedUrl: async (_c, command) => `https://signed.r2.test/${command.input.Key}` },
});

const { GET: report } = await import('../src/app/api/reports/[incidentId]/route.ts');
const { GET: versions } = await import('../src/app/api/reports/[incidentId]/revisions/route.ts');
const { GET: evidenceImage } = await import('../src/app/api/reports/[incidentId]/evidence-image/route.ts');
await import('../src/modules/contract/infrastructure/loader.ts');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => {
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test',
    INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a',
    R2_ACCESS_KEY: 'b',
    R2_SECRET_KEY: 'c',
    R2_BUCKET: 'd',
  });
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

const A = 'p55-a.mp4';
const B = 'p55-b.mp4';
const GONE = 'p55-gone.mp4';
const valid = JSON.parse(readFileSync(join(process.cwd(), '..', 'contracts', 'fixtures', 'valid', 'minimal-report.json'), 'utf8'));
const camera = (video, report = valid) => ({ video, report });
const envelope = (cameras) => ({
  overview: { title: 'Two vans', type: 'Theft', severity_level: 2, description: 'Combined', location: null },
  cameras,
});
const revision = (id, no, names, cameras, extra = {}) => ({
  id,
  incident_id: 1,
  revision_no: no,
  kind: 'ai',
  model_run_id: 'p55-run',
  parent_id: null,
  payload: envelope(cameras),
  evidence: [],
  video_names: names,
  created_by: null,
  created_at: `2026-10-01T0${no}:00:00`,
  note: null,
  ...extra,
});

/** Incident 1 holds A and B. Version 1 covers A, B and a since removed video; version 2 covers A only. */
function database() {
  const db = fakePostgrest(
    {
      incidents: [
        { id: 1, official_revision_id: 1, official_since: '2026-10-02T00:00:00', created_at: '2026-10-01T00:00:00' },
        { id: 2, official_revision_id: null, official_since: null, created_at: '2026-10-01T00:00:00' },
      ],
      videos: [
        {
          id: A,
          incident_id: 1,
          filepath: `videos/${A}`,
          uploaded_datetime: '2026-10-01T01:00:00',
          recorded_at: null,
          duration: 10,
          source: 'upload',
        },
        {
          id: B,
          incident_id: 1,
          filepath: `videos/${B}`,
          uploaded_datetime: '2026-10-01T02:00:00',
          recorded_at: null,
          duration: 12,
          source: 'upload',
        },
      ],
      model_runs: [{ id: 'p55-run', model_name: 'model-x', prompt_version: 'v4', run_datetime: '2026-10-01T00:30:00', notes: null }],
      report_revisions: [
        revision(1, 1, [A, B, GONE], [camera(A), camera(B, { not: 'a report' }), camera(GONE)], {
          evidence: [{ item_type: 'entity', item_id: 'E1', video: A, image: `evidence/videos/${A}/E1.jpg` }],
        }),
        revision(2, 2, [A], [camera(A)]),
      ],
      evidence_crops: [],
    },
    { rpc: {}, identity: { report_revisions: 'id' } },
  );
  globalThis.fetch = db.fetch;
  return db;
}

const on = (id) => ({ params: Promise.resolve({ incidentId: id }) });
const getReport = (id, query = '') => report(new Request(`http://localhost/api/reports/${id}${query}`), on(id));

test('the official version is shown by default with its coverage verdict, its cameras and the first camera that can be shown', async () => {
  database();
  const response = await getReport('1');
  assert.equal(response.status, 200);
  const { report: view } = await response.json();
  assert.equal(view.incidentId, 1);
  assert.equal(view.revision.revisionId, 1);
  assert.equal(view.officialRevisionId, 1);
  assert.equal(view.coverage.verdict.status, 'removed');
  assert.match(view.coverage.note, new RegExp(`Includes a removed video: ${GONE}`));
  assert.deepEqual(
    view.cameras.map((c) => [c.video, c.current, c.valid]),
    [
      [A, true, true],
      [B, true, false],
      [GONE, false, true],
    ],
  );
  assert.equal(view.camera, A);
  assert.equal(view.report.run.playbackUrl, `https://signed.r2.test/videos/${A}`);
});

test('another version and camera can be asked for; a camera of a removed video gets no playback, an invalid one no report', async () => {
  database();
  const latest = (await (await getReport('1', '?revision=2')).json()).report;
  assert.equal(latest.coverage.verdict.status, 'lacks');
  assert.match(latest.coverage.note, new RegExp(`Does not include: ${B}`));

  const removed = (await (await getReport('1', `?revision=1&camera=${GONE}`)).json()).report;
  assert.equal(removed.camera, GONE);
  assert.equal(removed.report.run.playbackUrl, '');

  const invalid = (await (await getReport('1', `?revision=1&camera=${B}`)).json()).report;
  assert.equal(invalid.camera, B);
  assert.equal(invalid.report, null);
});

test('a bad id, revision, an unknown incident, revision or camera are refused', async () => {
  database();
  for (const bad of ['0', '-1', '1.5', 'abc', '01']) assert.equal((await getReport(bad)).status, 400, bad);
  for (const bad of ['0', '-1', 'abc']) assert.equal((await getReport('1', `?revision=${bad}`)).status, 400, bad);
  assert.equal((await getReport('9')).status, 404);
  assert.equal((await getReport('1', '?revision=9')).status, 404);
  assert.equal((await getReport('2')).status, 404, 'an incident without a version');
  assert.equal((await getReport('1', '?camera=nope.mp4')).status, 404);
});

test('the versions are listed newest first, each with its coverage verdict', async () => {
  database();
  const response = await versions(new Request('http://localhost/api/reports/1/revisions'), on('1'));
  assert.equal(response.status, 200);
  const { revisions } = await response.json();
  assert.deepEqual(
    revisions.map((r) => [r.revisionNo, r.isOfficial, r.coverage.verdict.status]),
    [
      [2, false, 'lacks'],
      [1, true, 'removed'],
    ],
  );
  assert.deepEqual((await (await versions(new Request('http://localhost/x'), on('9'))).json()).revisions, []);
  assert.equal((await versions(new Request('http://localhost/x'), on('abc'))).status, 400);
});

test('an evidence image is signed only through a video that covers it', async () => {
  database();
  const get = (query, id = '1') => evidenceImage(new Request(`http://localhost/api/reports/${id}/evidence-image${query}`), on(id));
  const key = `evidence/videos/${A}/E1.jpg`;
  const ok = await get(`?video=${A}&image=${encodeURIComponent(key)}`);
  assert.equal(ok.status, 200);
  assert.deepEqual(await ok.json(), { url: `https://signed.r2.test/${key}` });
  assert.equal((await get(`?video=${B}&image=${encodeURIComponent(key)}`)).status, 404, 'through another video');
  assert.equal((await get(`?video=${A}&image=${encodeURIComponent(key)}`, '2')).status, 404, 'through another incident');
  assert.equal((await get(`?video=${A}&image=evidence%2Fother.jpg`)).status, 404, 'a key nothing refers to');
  assert.equal((await get(`?video=${A}`)).status, 400);
  assert.equal((await get(`?video=${A}&image=x`, 'abc')).status, 400);
});
