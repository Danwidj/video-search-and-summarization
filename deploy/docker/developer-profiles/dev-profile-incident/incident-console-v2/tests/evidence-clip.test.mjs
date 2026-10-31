// SPDX-License-Identifier: Apache-2.0

// Evidence clips: the clip window, the cache key, the pop-up button's states, the use case's cut-once caching, the ffmpeg
// arguments, and POST /api/reports/[videoId]/evidence-clip with fake PostgREST, R2 and ffmpeg.

import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { readFileSync, writeFileSync } from 'node:fs';
import { readFile } from 'node:fs/promises';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const commands = [];
const stored = new Set();
mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        commands.push(command);
        const name = command.constructor.name;
        if (name === 'HeadObjectCommand') {
          const key = command.input.Key;
          if (key.startsWith('evidence/') && !stored.has(key)) {
            return Promise.reject(Object.assign(new Error('NotFound'), { name: 'NotFound', $metadata: { httpStatusCode: 404 } }));
          }
          if (key === 'missing/video.mp4') {
            return Promise.reject(Object.assign(new Error('NotFound'), { name: 'NotFound', $metadata: { httpStatusCode: 404 } }));
          }
          return Promise.resolve({ ContentLength: 1000 });
        }
        if (name === 'PutObjectCommand') stored.add(command.input.Key);
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

const spawned = [];
let ffmpegBehaviour = 'ok';
mock.module('node:child_process', {
  namedExports: {
    spawn(command, args) {
      spawned.push({ command, args });
      const child = new EventEmitter();
      child.stdout = new EventEmitter();
      child.stderr = new EventEmitter();
      child.kill = () => {};
      setImmediate(() => {
        if (ffmpegBehaviour === 'missing') return child.emit('error', Object.assign(new Error('spawn ffmpeg ENOENT'), { code: 'ENOENT' }));
        if (ffmpegBehaviour === 'ok') writeFileSync(args.at(-1), 'MP4BYTES');
        if (ffmpegBehaviour === 'fail') child.stderr.emit('data', Buffer.from('Invalid data found when processing input'));
        child.emit('close', ffmpegBehaviour === 'fail' ? 1 : 0);
      });
      return child;
    },
  },
});

const { CLIP_SECONDS, clipButton, clipCentreSeconds, clipWindow, evidenceClipKey, evidenceClipUrl } = await import(
  '../src/modules/reports/domain/evidence-clip.ts'
);
const { resolveHostBinary } = await import('../src/lib/video/host-binaries.ts');
const { getEvidenceClip } = await import('../src/modules/reports/application/get-evidence-clip/index.ts');
const { getReport } = await import('../src/modules/reports/application/get-report/index.ts');
const { InMemoryIncidentRepository } = await import('../src/modules/reports/infrastructure/memory/incidents.ts');
const { structuredFromPayload } = await import('../src/modules/reports/domain/payload-view.ts');
const { ffmpegClipArguments } = await import('../src/lib/video/ffmpeg-clip.ts');
const { POST } = await import('../src/app/api/reports/[videoId]/evidence-clip/route.ts');
const { aiRevisionRow, aiRunReport } = await import('./support/report-view.mjs');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const VIDEO_KEY = smoke.video.filepath;
const RUN = `evidence/${VIDEO_KEY}/run-1`;
const CLIP_KEY = `${RUN}/E1-clip.mp4`;

const entry = (id, extra = {}) => ({
  item_type: 'entity',
  item_id: id,
  image: `${RUN}/${id}.jpg`,
  frame: `${RUN}/${id}-frame.jpg`,
  bounding_box: [100, 100, 500, 400],
  timestamp_seconds: 6,
  box_seconds: 7,
  ...extra,
});

test('the clip is CLIP_SECONDS centred on the second, shifted to stay inside the video', () => {
  assert.equal(CLIP_SECONDS, 4);
  assert.deepEqual(clipWindow(10, 30), { startSeconds: 8, lengthSeconds: 4 });
  assert.deepEqual(clipWindow(0.5, 30), { startSeconds: 0, lengthSeconds: 4 }, 'clamped at the start');
  assert.deepEqual(clipWindow(29.5, 30), { startSeconds: 26, lengthSeconds: 4 }, 'clamped at the end');
  assert.deepEqual(clipWindow(1.2, 2.5), { startSeconds: 0, lengthSeconds: 2.5 }, 'a short video is clipped whole');
  assert.deepEqual(clipWindow(1, 4), { startSeconds: 0, lengthSeconds: 4 });
  assert.deepEqual(clipWindow(1, null), { startSeconds: 0, lengthSeconds: 4 }, 'unknown length: only the start is clamped');
  assert.deepEqual(clipWindow(100, null), { startSeconds: 98, lengthSeconds: 4 });
  assert.deepEqual(clipWindow(10.1234, 30.98765), { startSeconds: 8.123, lengthSeconds: 4 });
});

test('the clip is centred on the box second, else the entry second, and needs one of them', () => {
  assert.equal(clipCentreSeconds({ boxSeconds: 7, timestampSeconds: 6 }), 7);
  assert.equal(clipCentreSeconds({ boxSeconds: null, timestampSeconds: 6 }), 6);
  assert.equal(clipCentreSeconds({ boxSeconds: 0, timestampSeconds: 6 }), 0);
  assert.equal(clipCentreSeconds({ boxSeconds: null, timestampSeconds: null }), null);
  assert.equal(clipCentreSeconds({ boxSeconds: -1, timestampSeconds: null }), null);
});

test('the clip is cached beside the first stored evidence object of the video, or nowhere', () => {
  assert.equal(evidenceClipKey([`${RUN}/E1-frame.jpg`, `${RUN}/E1.jpg`], VIDEO_KEY, 'E1'), CLIP_KEY);
  assert.equal(evidenceClipKey([null, `evidence/${VIDEO_KEY}/edit-2/E1.jpg`], VIDEO_KEY, 'E1'), `evidence/${VIDEO_KEY}/edit-2/E1-clip.mp4`);
  assert.equal(evidenceClipKey([null, null, `${RUN}/E1-track.json`], VIDEO_KEY, 'E1'), CLIP_KEY);
  assert.equal(evidenceClipKey([null, null, null], VIDEO_KEY, 'E1'), null, 'no stored evidence');
  assert.equal(evidenceClipKey(['evidence/other.mp4/run-1/E1.jpg'], VIDEO_KEY, 'E1'), null, "another video's folder");
  assert.equal(evidenceClipKey([`evidence/${VIDEO_KEY}/../x/E1.jpg`], VIDEO_KEY, 'E1'), null);
  assert.equal(evidenceClipKey([`${RUN}/E1.jpg`], VIDEO_KEY, '../E1'), null, 'an unsafe item id');
  assert.match(evidenceClipUrl('v 1', 3, 'entity', 'E1'), /^\/api\/reports\/v%201\/evidence-clip\?revision=3&type=entity&item=E1$/);
});

test('the Play clip button: idle, cutting (disabled), gone once playing, and Try again after a failure', () => {
  assert.deepEqual(clipButton({ status: 'idle' }), { label: 'Play clip', disabled: false, visible: true });
  assert.deepEqual(clipButton({ status: 'loading' }), { label: 'Cutting clip…', disabled: true, visible: true });
  assert.equal(clipButton({ status: 'ready', url: 'u' }).visible, false);
  assert.deepEqual(clipButton({ status: 'error', message: 'x' }), { label: 'Try again', disabled: false, visible: true });
});

test('the dialog shows Play clip only for an item with a clip URL, and plays the clip with controls', () => {
  const source = readFileSync(
    join(process.cwd(), 'src', 'sections', 'reports', 'components', 'EvidenceDetailDialog', 'EvidenceDetailDialog.tsx'),
    'utf8',
  );
  assert.match(source, /clipUrl && clipControl\.visible &&/);
  assert.match(source, /<video[\s\S]*?controls[\s\S]*?src=\{clip\.url\}/);
  assert.match(source, /data-testid="evidence-dialog-clip-error"/, 'a failure is shown in the pop-up');
  assert.match(source, /<EvidenceFrame/, 'the frame and box stay');
});

function clipRecord(evidence) {
  const record = aiRunReport(smoke);
  record.evidence = evidence;
  record.entities = structuredFromPayload(record.payload, record.evidence).entities;
  return record;
}

test('getReport gives a clip URL only to an item with a second and stored evidence', async () => {
  const incidents = new InMemoryIncidentRepository([clipRecord([entry('E1'), entry('E2', { image: null, frame: null, track: null })])]);
  const view = await getReport(incidents, smoke.videoId, null, async (key) => `https://signed/${key}`);
  const [e1, e2] = view.structured.entities;
  assert.equal(e1.evidence.clipUrl, evidenceClipUrl(smoke.videoId, view.revisionId, 'entity', 'E1'));
  assert.equal(e2.evidence.clipUrl, null);
});

function fakeStore({ duration = 30, cut = async () => new Uint8Array([1]) } = {}) {
  const keys = new Set();
  const calls = { cut: [], put: [] };
  return {
    calls,
    keys,
    exists: async (key) => keys.has(key),
    durationSeconds: async () => duration,
    cut: async (videoKey, window) => {
      calls.cut.push({ videoKey, window });
      return cut();
    },
    put: async (key) => {
      calls.put.push(key);
      keys.add(key);
    },
    sign: async (key) => `signed:${key}`,
  };
}

test('the first play cuts and stores the clip, a second play signs the stored one, and concurrent plays cut once', async () => {
  const incidents = new InMemoryIncidentRepository([clipRecord([entry('E1'), entry('E2')])]);
  const { revisionId } = (await incidents.getRevision(smoke.videoId, null)).revision;
  const store = fakeStore();
  const request = { videoId: smoke.videoId, revisionId, itemType: 'entity', itemId: 'E1' };
  assert.equal(await getEvidenceClip(incidents, store, request), `signed:${CLIP_KEY}`);
  assert.deepEqual(store.calls.cut, [{ videoKey: VIDEO_KEY, window: { startSeconds: 5, lengthSeconds: 4 } }], 'centred on the box second');
  assert.equal(await getEvidenceClip(incidents, store, request), `signed:${CLIP_KEY}`);
  assert.equal(store.calls.cut.length, 1, 'the stored clip is reused');

  const both = await Promise.all([1, 2, 3].map(() => getEvidenceClip(incidents, store, { ...request, itemId: 'E2' })));
  assert.deepEqual(new Set(both), new Set([`signed:${RUN}/E2-clip.mp4`]));
  assert.equal(store.calls.cut.length, 2, 'three concurrent plays cut once');
});

test('the use case refuses an unknown version or item, a missing second or folder, and a second past the end', async () => {
  const incidents = new InMemoryIncidentRepository([
    clipRecord([entry('E1'), entry('E2', { box_seconds: null, timestamp_seconds: null }), entry('E3', { image: null, frame: null })]),
  ]);
  const { revisionId } = (await incidents.getRevision(smoke.videoId, null)).revision;
  const request = { videoId: smoke.videoId, revisionId, itemType: 'entity', itemId: 'E1' };
  const refused = async (overrides, status, store = fakeStore()) => {
    await assert.rejects(getEvidenceClip(incidents, store, { ...request, ...overrides }), (error) => error.status === status);
    assert.equal(store.calls.cut.length, 0);
  };
  await refused({ revisionId: revisionId + 50 }, 404);
  await refused({ itemId: 'E9' }, 404);
  await refused({ itemType: 'asset' }, 404);
  await refused({ itemId: 'E2' }, 422);
  await refused({ itemId: 'E3' }, 422);
  await refused({}, 422, fakeStore({ duration: 7 }));
  const missing = fakeStore();
  missing.durationSeconds = async () => {
    throw new Error('NotFound');
  };
  await refused({}, 409, missing);
});

test('a failed cut stores nothing and the next play tries again', async () => {
  const incidents = new InMemoryIncidentRepository([clipRecord([entry('E1')])]);
  const { revisionId } = (await incidents.getRevision(smoke.videoId, null)).revision;
  const request = { videoId: smoke.videoId, revisionId, itemType: 'entity', itemId: 'E1' };
  let fail = true;
  const store = fakeStore({
    cut: async () => {
      if (fail) throw Object.assign(new Error('ffmpeg could not cut the clip'), { status: 502 });
      return new Uint8Array([1]);
    },
  });
  await assert.rejects(getEvidenceClip(incidents, store, request), /could not cut/);
  assert.deepEqual(store.calls.put, []);
  fail = false;
  assert.equal(await getEvidenceClip(incidents, store, request), `signed:${CLIP_KEY}`);
});

test('ffmpeg cuts a video-only, faststart H.264 MP4 no larger than 1080p from the signed URL', () => {
  const args = ffmpegClipArguments('https://signed/v.mp4', { startSeconds: 5, lengthSeconds: 4 }, '/tmp/x/clip.mp4');
  const after = (flag) => args[args.indexOf(flag) + 1];
  assert.equal(after('-ss'), '5');
  assert.equal(after('-t'), '4');
  assert.ok(args.indexOf('-ss') < args.indexOf('-i'), 'seeks the input, so only the clip is read');
  assert.equal(after('-c:v'), 'libx264');
  assert.equal(after('-pix_fmt'), 'yuv420p');
  assert.equal(after('-movflags'), '+faststart');
  assert.equal(after('-map'), '0:v:0');
  assert.ok(args.includes('-an'), 'no audio track');
  assert.match(after('-vf'), /min\(iw,1920\).*min\(ih,1080\).*force_original_aspect_ratio=decrease/);
  assert.equal(args.at(-1), '/tmp/x/clip.mp4');
});

// The route over fake PostgREST, R2 and ffmpeg.

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => {
  commands.length = 0;
  spawned.length = 0;
  stored.clear();
  ffmpegBehaviour = 'ok';
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

function database(video = smoke.video) {
  globalThis.fetch = fakePostgrest({
    videos: [{ ...video, official_revision_id: null }],
    model_runs: [smoke.modelRun],
    report_revisions: [aiRevisionRow(smoke, { evidence: [entry('E1'), entry('E2', { image: null, frame: null })] })],
  }).fetch;
}

const post = (query) =>
  POST(new Request(`http://localhost/api/reports/${smoke.videoId}/evidence-clip${query}`, { method: 'POST' }), {
    params: Promise.resolve({ videoId: smoke.videoId }),
  });

test('the route cuts the clip once from the signed video URL, stores it as video/mp4 and answers a signed URL', async () => {
  database();
  const first = await post('?revision=1&type=entity&item=E1');
  assert.equal(first.status, 200);
  assert.equal(first.headers.get('cache-control'), 'no-store');
  assert.deepEqual(await first.json(), { url: `https://signed.r2.test/${CLIP_KEY}` });
  assert.equal(spawned.length, 1);
  assert.equal(spawned[0].command, resolveHostBinary('ffmpeg'), 'the clip is cut with the resolved ffmpeg');
  assert.equal(spawned[0].args[spawned[0].args.indexOf('-i') + 1], `https://signed.r2.test/${VIDEO_KEY}`);
  const put = commands.find((c) => c.constructor.name === 'PutObjectCommand');
  assert.equal(put.input.Key, CLIP_KEY);
  assert.equal(put.input.ContentType, 'video/mp4');
  assert.equal(put.input.IfNoneMatch, '*', 'a stored clip is never overwritten');

  const second = await post('?revision=1&type=entity&item=E1');
  assert.equal(second.status, 200);
  assert.equal(spawned.length, 1, 'the second play reuses the stored clip');
});

test('the route answers clear errors for a bad query, an item without a clip, a missing video and ffmpeg failures', async () => {
  database();
  assert.equal((await post('')).status, 400);
  assert.equal((await post('?revision=1&type=person&item=E1')).status, 400);
  assert.equal((await post('?revision=1&type=entity&item=../E1')).status, 400);
  assert.equal((await post('?revision=9&type=entity&item=E1')).status, 404);
  const noFolder = await post('?revision=1&type=entity&item=E2');
  assert.equal(noFolder.status, 422);
  assert.match((await noFolder.json()).error, /no stored evidence/);

  ffmpegBehaviour = 'missing';
  const missing = await post('?revision=1&type=entity&item=E1');
  assert.equal(missing.status, 503);
  assert.match((await missing.json()).error, /ffmpeg is not installed/);
  ffmpegBehaviour = 'fail';
  const failed = await post('?revision=1&type=entity&item=E1');
  assert.equal(failed.status, 502);
  const message = (await failed.json()).error;
  assert.match(message, /ffmpeg could not cut the clip: Invalid data/);
  assert.doesNotMatch(message, /signed|evidence\//, 'no key or signed URL in the error');
  ffmpegBehaviour = 'empty';
  assert.equal((await post('?revision=1&type=entity&item=E1')).status, 502);
  assert.equal(
    commands.some((c) => c.constructor.name === 'PutObjectCommand'),
    false,
    'nothing is stored when the cut fails',
  );
});

test('the route answers 409 when the video file is missing from R2', async () => {
  const run = 'evidence/missing/video.mp4/run-1';
  globalThis.fetch = fakePostgrest({
    videos: [{ ...smoke.video, filepath: 'missing/video.mp4', official_revision_id: null }],
    model_runs: [smoke.modelRun],
    report_revisions: [aiRevisionRow(smoke, { evidence: [entry('E1', { image: `${run}/E1.jpg`, frame: `${run}/E1-frame.jpg` })] })],
  }).fetch;
  const gone = await post('?revision=1&type=entity&item=E1');
  assert.equal(gone.status, 409);
  assert.match((await gone.json()).error, /video file is missing/);
  assert.equal(spawned.length, 0);
});

test('the temporary clip file is removed after the cut', async () => {
  database();
  await post('?revision=1&type=entity&item=E1');
  const output = spawned[0].args.at(-1);
  await assert.rejects(readFile(output), { code: 'ENOENT' });
});
