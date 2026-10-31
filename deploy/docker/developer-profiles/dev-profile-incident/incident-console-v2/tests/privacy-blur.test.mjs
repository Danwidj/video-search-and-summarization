// SPDX-License-Identifier: Apache-2.0

// Privacy blur: the head-region maths (the agent's own), the regions and ffmpeg filter of a blurred evidence clip, the
// clip use case and route with a fake ffmpeg, the face-blur toggle (use case and PUT /api/videos/[videoId]/privacy),
// the re-analysis job it queues, and the report view's badge flag.

import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { readFileSync, writeFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { afterEach, beforeEach, mock, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const commands = [];
mock.module('@aws-sdk/client-s3', {
  namedExports: {
    S3Client: class {
      send(command) {
        commands.push(command);
        const name = command.constructor.name;
        if (name === 'HeadObjectCommand') {
          if (command.input.Key.startsWith('evidence/'))
            return Promise.reject(Object.assign(new Error('NotFound'), { name: 'NotFound', $metadata: { httpStatusCode: 404 } }));
          return Promise.resolve({ ContentLength: 1000 });
        }
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
mock.module('node:child_process', {
  namedExports: {
    spawn(command, args) {
      spawned.push({ command, args });
      const child = new EventEmitter();
      child.stdout = new EventEmitter();
      child.stderr = new EventEmitter();
      child.kill = () => {};
      setImmediate(() => {
        writeFileSync(args.at(-1), 'MP4BYTES');
        child.emit('close', 0);
      });
      return child;
    },
  },
});

const privacy = await import('../src/modules/reports/domain/privacy-blur.ts');
const { evidenceClipKey } = await import('../src/modules/reports/domain/evidence-clip.ts');
const { ffmpegClipArguments } = await import('../src/lib/video/ffmpeg-clip.ts');
const { getEvidenceClip } = await import('../src/modules/reports/application/get-evidence-clip/index.ts');
const { InMemoryIncidentRepository } = await import('../src/modules/reports/infrastructure/memory/incidents.ts');
const { structuredFromPayload } = await import('../src/modules/reports/domain/payload-view.ts');
const { setVideoPrivacy } = await import('../src/modules/videos/application/set-video-privacy.ts');
const { InMemoryVideoRepository } = await import('../src/modules/videos/infrastructure/memory/videos.ts');
const { InMemoryAnalysisJobRepository } = await import('../src/modules/jobs/infrastructure/memory/analysis-jobs.ts');
const { jobFromRow } = await import('../src/modules/jobs/infrastructure/supabase/analysis-jobs.ts');
const { jobVideoId } = await import('../src/modules/jobs/application/index.ts');
const { StoreRejection } = await import('../src/modules/shared/domain/common.ts');
const clipRoute = await import('../src/app/api/reports/[videoId]/evidence-clip/route.ts');
const privacyRoute = await import('../src/app/api/videos/[videoId]/privacy/route.ts');
const { aiRevisionRow, aiRunReport, buildReportView } = await import('./support/report-view.mjs');
const { fakePostgrest } = await import('./support/fake-postgrest.mjs');

const smoke = JSON.parse(readFileSync(join(process.cwd(), 'tests', 'fixtures', 'contract-v2-smoke-run.json'), 'utf8'));
const VIDEO_KEY = smoke.video.filepath;
const RUN = `evidence/${VIDEO_KEY}/run-1`;

// --- the head region and the clip regions -------------------------------------------------------------------------

test('the head region is the top 30 % of a person box, raised and widened by 10 %, clamped to the frame (as in the agent)', () => {
  assert.deepEqual(privacy.headRegion([200, 400, 600, 500]), [160, 390, 320, 510]);
  assert.deepEqual(privacy.headRegion([0, 0, 1000, 1000]), [0, 0, 300, 1000]);
  assert.deepEqual(privacy.headRegion([10, 980, 410, 1000]), [0, 978, 130, 1000]);
  assert.deepEqual(privacy.padBox([100, 100, 200, 300], 0.25), [75, 50, 225, 350]);
  assert.deepEqual(privacy.padBox([0, 900, 100, 1000], 0.5), [0, 850, 150, 1000]);
});

test('a run is blurred only when its notes carry the agent privacy summary with blur_faces true', () => {
  assert.equal(privacy.runBlurredFaces({ privacy: { blur_faces: true, regions: 2 } }), true);
  assert.equal(privacy.runBlurredFaces({ privacy: { blur_faces: false } }), false);
  assert.equal(privacy.runBlurredFaces({}), false);
  assert.equal(privacy.runBlurredFaces(null), false);
  assert.deepEqual(privacy.recordedBlurRegions([[1, 2, 30, 40], [5, 5, 5, 9], 'x']), [[1, 2, 30, 40]]);
  assert.equal(privacy.recordedBlurRegions(undefined), null);
});

const WINDOW = { startSeconds: 5, lengthSeconds: 4 };

test("a blurred clip blurs the item's track per second and the recorded heads for the whole clip", () => {
  const track = [
    { t: 4.0, box: [0, 0, 100, 100] }, // before the clip (beyond the half-second margin): ignored
    { t: 5.2, box: [100, 100, 500, 300] },
    { t: 5.6, box: [120, 140, 520, 340] },
    { t: 7.1, box: [200, 200, 600, 400] },
  ];
  const regions = privacy.clipBlurRegions({ window: WINDOW, track, recorded: [[600, 600, 700, 700]], personBox: [1, 1, 900, 900] });
  assert.deepEqual(regions, [
    { box: [60, 80, 240, 360], fromSeconds: 0, toSeconds: 1 }, // the union of the two heads in the clip's first second
    { box: [160, 180, 320, 420], fromSeconds: 2, toSeconds: 3 },
    { box: [575, 575, 725, 725], fromSeconds: null, toSeconds: null }, // recorded at the item's second, padded for movement
  ]);
});

test("without recorded heads a person's own head stands in for the whole clip; with nothing known no blurred clip is cut", () => {
  assert.deepEqual(privacy.clipBlurRegions({ window: WINDOW, track: null, recorded: null, personBox: [200, 400, 600, 500] }), [
    { box: [120, 360, 360, 540], fromSeconds: null, toSeconds: null },
  ]);
  assert.equal(privacy.clipBlurRegions({ window: WINDOW, track: null, recorded: null, personBox: null }), null);
  assert.deepEqual(privacy.clipBlurRegions({ window: WINDOW, track: [], recorded: [], personBox: null }), [], 'the agent saw no head');
  assert.deepEqual(
    privacy.clipBlurRegions({ window: WINDOW, track: null, recorded: [[0, 0, 4, 900]], personBox: null }),
    [],
    'a sliver would crop to zero pixels (the whole frame for ffmpeg), so it is dropped',
  );
  const many = Array.from({ length: 50 }, (_, i) => [i, i, i + 100, i + 100]);
  assert.equal(privacy.clipBlurRegions({ window: WINDOW, track: null, recorded: many, personBox: null }).length, privacy.MAX_CLIP_REGIONS);
});

test('the clip filter scales, then box-blurs each region over its span, and ends on [blurred]', () => {
  const filter = privacy.clipBlurFilter('scale=w=640:h=-2', [
    { box: [100, 200, 300, 500], fromSeconds: 0, toSeconds: 1 },
    { box: [0, 0, 500, 500], fromSeconds: null, toSeconds: null },
  ]);
  assert.equal(
    filter,
    [
      '[0:v:0]scale=w=640:h=-2[v0]',
      '[v0]split[m0][c0]',
      "[c0]crop=w='2*trunc(iw*0.3000/2)':h='2*trunc(ih*0.2000/2)':x='2*trunc(iw*0.2000/2)':y='2*trunc(ih*0.1000/2)',boxblur=luma_radius='max(0,min(w,h)/2-1)':luma_power=3:chroma_radius='max(0,min(cw,ch)/2-1)':chroma_power=3[k0]",
      "[m0][k0]overlay=x='2*trunc(main_w*0.2000/2)':y='2*trunc(main_h*0.1000/2)':enable='between(t,0,1)'[v1]",
      '[v1]split[m1][c1]',
      "[c1]crop=w='2*trunc(iw*0.5000/2)':h='2*trunc(ih*0.5000/2)':x='2*trunc(iw*0.0000/2)':y='2*trunc(ih*0.0000/2)',boxblur=luma_radius='max(0,min(w,h)/2-1)':luma_power=3:chroma_radius='max(0,min(cw,ch)/2-1)':chroma_power=3[k1]",
      "[m1][k1]overlay=x='2*trunc(main_w*0.0000/2)':y='2*trunc(main_h*0.0000/2)'[v2]",
      '[v2]null[blurred]',
    ].join(';'),
  );
});

test('ffmpeg uses the blur filter graph only when there are regions, and never maps audio', () => {
  const plain = ffmpegClipArguments('https://signed/v.mp4', WINDOW, '/tmp/x/clip.mp4', []);
  assert.ok(plain.includes('-vf') && !plain.includes('-filter_complex'));
  assert.deepEqual(plain, ffmpegClipArguments('https://signed/v.mp4', WINDOW, '/tmp/x/clip.mp4'));
  const blurred = ffmpegClipArguments('https://signed/v.mp4', WINDOW, '/tmp/x/clip.mp4', [
    { box: [0, 0, 500, 500], fromSeconds: null, toSeconds: null },
  ]);
  const after = (flag) => blurred[blurred.indexOf(flag) + 1];
  assert.ok(!blurred.includes('-vf'));
  assert.match(after('-filter_complex'), /^\[0:v:0\]scale=w='min\(iw,1920\)'.*\[blurred\]$/);
  assert.equal(after('-map'), '[blurred]');
  assert.ok(blurred.includes('-an'));
  assert.equal(after('-c:v'), 'libx264');
  assert.equal(blurred.at(-1), '/tmp/x/clip.mp4');
});

test('a blurred clip is cached under its own key, so an unblurred clip is never served in its place', () => {
  const keys = [`${RUN}/E1-frame.jpg`];
  assert.equal(evidenceClipKey(keys, VIDEO_KEY, 'E1'), `${RUN}/E1-clip.mp4`);
  assert.equal(evidenceClipKey(keys, VIDEO_KEY, 'E1', true), `${RUN}/E1-clip-blur.mp4`);
});

// --- the clip use case ---------------------------------------------------------------------------------------------

const entry = (id, extra = {}) => ({
  item_type: 'entity',
  item_id: id,
  image: `${RUN}/${id}.jpg`,
  frame: `${RUN}/${id}-frame.jpg`,
  bounding_box: [100, 100, 500, 400],
  located: true,
  timestamp_seconds: 6,
  box_seconds: 7,
  ...extra,
});

function clipRecord(evidence, { blurFaces = false, runBlurred = false } = {}) {
  const record = aiRunReport(smoke);
  record.evidence = evidence;
  record.entities = structuredFromPayload(record.payload, record.evidence).entities;
  record.video = { ...record.video, blurFaces };
  if (runBlurred && record.modelRun?.notes.kind === 'contract') {
    record.modelRun.notes.response = { ...record.modelRun.notes.response, privacy: { blur_faces: true } };
  }
  return record;
}

function fakeStore(json = {}) {
  const calls = { cut: [], put: [], read: [] };
  return {
    calls,
    exists: async () => false,
    durationSeconds: async () => 30,
    cut: async (videoKey, window, regions) => {
      calls.cut.push({ videoKey, window, regions });
      return new Uint8Array([1]);
    },
    readJson: async (key) => {
      calls.read.push(key);
      if (!(key in json)) throw new Error('NotFound');
      return json[key];
    },
    put: async (key) => calls.put.push(key),
    sign: async (key) => `signed:${key}`,
  };
}

async function clipFor(record, itemId, store, itemType = 'entity') {
  const incidents = new InMemoryIncidentRepository([record]);
  const { revisionId } = (await incidents.getRevision(smoke.videoId, null)).revision;
  return getEvidenceClip(incidents, store, { videoId: smoke.videoId, revisionId, itemType, itemId });
}

test('a video without the toggle, analysed without blur, gets its plain clip', async () => {
  const store = fakeStore();
  assert.equal(await clipFor(clipRecord([entry('E1')]), 'E1', store), `signed:${RUN}/E1-clip.mp4`);
  assert.equal(store.calls.cut[0].regions, undefined);
  assert.deepEqual(store.calls.read, []);
});

test("the toggle on: the clip is cut blurred from the item's track and recorded heads, under the -clip-blur key", async () => {
  const trackKey = `${RUN}/E1-track.json`;
  const store = fakeStore({ [trackKey]: [{ t: 6.5, box: [100, 100, 500, 400], score: 0.9 }] });
  const record = clipRecord([entry('E1', { track: trackKey, blur_regions: [[300, 600, 400, 700]] })], { blurFaces: true });
  assert.equal(await clipFor(record, 'E1', store), `signed:${RUN}/E1-clip-blur.mp4`);
  assert.deepEqual(store.calls.put, [`${RUN}/E1-clip-blur.mp4`]);
  assert.deepEqual(store.calls.read, [trackKey]);
  const [{ window, regions }] = store.calls.cut;
  assert.deepEqual(window, { startSeconds: 5, lengthSeconds: 4 });
  assert.deepEqual(regions, [
    { box: [60, 70, 220, 430], fromSeconds: 1, toSeconds: 2 },
    { box: [275, 575, 425, 725], fromSeconds: null, toSeconds: null },
  ]);
});

test('a run analysed with blur gets a blurred clip even after the toggle was switched off', async () => {
  const store = fakeStore();
  const record = clipRecord([entry('E1', { blur_regions: [] })], { runBlurred: true });
  assert.equal(await clipFor(record, 'E1', store), `signed:${RUN}/E1-clip-blur.mp4`);
  assert.deepEqual(store.calls.cut[0].regions, [], 'the agent saw no head at that second');
});

test('a blurred clip is refused when nothing is known about the heads, and when the track cannot be read', async () => {
  const instrument = entry('I1', { item_type: 'instrument' });
  await assert.rejects(
    clipFor(clipRecord([instrument], { blurFaces: true }), 'I1', fakeStore(), 'instrument'),
    (error) => error.status === 422,
  );
  const unreadable = clipRecord([entry('E1', { track: `${RUN}/E1-track.json` })], { blurFaces: true });
  const store = fakeStore();
  await assert.rejects(clipFor(unreadable, 'E1', store), (error) => error.status === 502);
  assert.deepEqual(store.calls.put, [], 'nothing is stored');
  // a person not located has no box of its own
  await assert.rejects(
    clipFor(clipRecord([entry('E2', { located: false, bounding_box: null })], { blurFaces: true }), 'E2', fakeStore()),
    (error) => error.status === 422,
  );
});

// --- the clip route, with the face-blur column, R2 and a fake ffmpeg -------------------------------------------------

const originalFetch = globalThis.fetch;
const originalEnv = { ...process.env };
beforeEach(() => {
  commands.length = 0;
  spawned.length = 0;
  Object.assign(process.env, {
    INCIDENT_SUPABASE_URL: 'https://supabase.test',
    INCIDENT_SUPABASE_SERVICE_ROLE_KEY: 'k',
    R2_ACCOUNT_ID: 'a',
    R2_ACCESS_KEY: 'b',
    R2_SECRET_KEY: 'c',
    R2_BUCKET: 'd',
    VLM_MODEL: 'nvidia/cosmos-3-nano-reasoner',
  });
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  process.env = { ...originalEnv };
});

test('the clip route reads videos.blur_faces and cuts the blurred clip through the filter graph', async () => {
  globalThis.fetch = fakePostgrest({
    videos: [{ ...smoke.video, official_revision_id: null, blur_faces: true }],
    model_runs: [smoke.modelRun],
    report_revisions: [aiRevisionRow(smoke, { evidence: [entry('E1')] })],
  }).fetch;
  const response = await clipRoute.POST(
    new Request(`http://localhost/api/reports/${smoke.videoId}/evidence-clip?revision=1&type=entity&item=E1`, { method: 'POST' }),
    { params: Promise.resolve({ videoId: smoke.videoId }) },
  );
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { url: `https://signed.r2.test/${RUN}/E1-clip-blur.mp4` });
  const args = spawned[0].args;
  assert.equal(args[args.indexOf('-map') + 1], '[blurred]');
  assert.match(args[args.indexOf('-filter_complex') + 1], /boxblur/);
  const put = commands.find((c) => c.constructor.name === 'PutObjectCommand');
  assert.equal(put.input.Key, `${RUN}/E1-clip-blur.mp4`);
});

// --- the toggle and its re-analysis job ------------------------------------------------------------------------------

const VIDEO = {
  videoId: 'v1',
  storageKey: 'uploads/cam/v1.mp4',
  uploadedAt: null,
  source: null,
  officialRevisionId: null,
  revisionIds: [],
};

test('switching the toggle stores it and queues one re-analysis of the video, asking for blur as switched', async () => {
  const videos = new InMemoryVideoRepository([VIDEO]);
  const jobs = new InMemoryAnalysisJobRepository();
  const on = await setVideoPrivacy({ videos, jobs }, 'v1', true, 'model-a');
  assert.equal((await videos.getVideo('v1')).blurFaces, true);
  assert.equal(on.blurFaces, true);
  assert.deepEqual(
    {
      filePath: on.job.filePath,
      filename: on.job.filename,
      model: on.job.model,
      reanalyseVideoId: on.job.reanalyseVideoId,
      blurFaces: on.job.blurFaces,
    },
    { filePath: 'uploads/cam/v1.mp4', filename: 'v1.mp4', model: 'model-a', reanalyseVideoId: 'v1', blurFaces: true },
  );
  assert.equal(jobVideoId(on.job), 'v1', 'the job analyses the existing video, not a new one');

  assert.equal((await setVideoPrivacy({ videos, jobs }, 'v1', true, 'model-a')).job, null, 'no change, no job');
  const off = await setVideoPrivacy({ videos, jobs }, 'v1', false, 'model-a');
  assert.equal(off.job.blurFaces, false);
  assert.equal((await videos.getVideo('v1')).blurFaces, false);
  assert.equal((await jobs.list(10)).length, 2);
});

test('the toggle refuses an unknown video or one without a stored file, and is put back when no job can be queued', async () => {
  const videos = new InMemoryVideoRepository([VIDEO, { ...VIDEO, videoId: 'v-vst', storageKey: '/vst/legacy.mp4' }]);
  const jobs = new InMemoryAnalysisJobRepository();
  await assert.rejects(
    setVideoPrivacy({ videos, jobs }, 'v-none', true, 'm'),
    (e) => e instanceof StoreRejection && e.reason === 'not-found',
  );
  await assert.rejects(setVideoPrivacy({ videos, jobs }, 'v-vst', true, 'm'), (e) => e instanceof StoreRejection && e.reason === 'invalid');
  jobs.enqueue = async () => {
    throw new Error('queue down');
  };
  await assert.rejects(setVideoPrivacy({ videos, jobs }, 'v1', true, 'm'), /queue down/);
  assert.equal((await videos.getVideo('v1')).blurFaces, false);
});

test('a job row maps its re-analysis target and blur flag; an upload job has neither', () => {
  const row = { id: 3, file_path: 'uploads/a.mp4', filename: 'a.mp4', model: null, status: 'queued', attempts: 0, created_at: 't' };
  assert.deepEqual([jobFromRow(row).reanalyseVideoId, jobFromRow(row).blurFaces], [null, false]);
  const job = jobFromRow({ ...row, reanalyse_video_id: 'v1', blur_faces: true });
  assert.deepEqual([job.reanalyseVideoId, job.blurFaces], ['v1', true]);
  assert.match(jobVideoId(jobFromRow(row)), /^v/);
  assert.notEqual(jobVideoId(jobFromRow(row)), 'v1');
});

const put = (body) =>
  privacyRoute.PUT(
    new Request('http://localhost/api/videos/v1/privacy', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ videoId: 'v1' }) },
  );

test('PUT /api/videos/[videoId]/privacy stores videos.blur_faces and inserts the re-analysis job', async () => {
  const db = fakePostgrest(
    { videos: [{ id: 'v1', filepath: 'uploads/cam/v1.mp4', official_revision_id: null, blur_faces: false }], analysis_jobs: [] },
    { identity: { analysis_jobs: 'id' } },
  );
  // The column defaults the database applies to a new job.
  globalThis.fetch = (url, init = {}) =>
    db.fetch(
      url,
      String(url).endsWith('/analysis_jobs') && init.method === 'POST'
        ? { ...init, body: JSON.stringify({ status: 'queued', attempts: 0, created_at: 't', ...JSON.parse(init.body) }) }
        : init,
    );
  assert.equal((await put({ blurFaces: 'yes' })).status, 400);
  assert.equal((await put({})).status, 400);
  const response = await put({ blurFaces: true });
  assert.equal(response.status, 200, JSON.stringify(await response.clone().json()));
  const { privacy: change } = await response.json();
  assert.equal(change.blurFaces, true);
  assert.equal(change.job.reanalyseVideoId, 'v1');
  assert.equal(db.store.videos[0].blur_faces, true);
  const [job] = db.store.analysis_jobs;
  assert.deepEqual(
    {
      file_path: job.file_path,
      filename: job.filename,
      model: job.model,
      reanalyse_video_id: job.reanalyse_video_id,
      blur_faces: job.blur_faces,
    },
    {
      file_path: 'uploads/cam/v1.mp4',
      filename: 'v1.mp4',
      model: 'nvidia/cosmos-3-nano-reasoner',
      reanalyse_video_id: 'v1',
      blur_faces: true,
    },
  );
});

test('PUT /api/videos/[videoId]/privacy answers 404 for an unknown video', async () => {
  globalThis.fetch = fakePostgrest({ videos: [], analysis_jobs: [] }).fetch;
  assert.equal((await put({ blurFaces: true })).status, 404);
});

// --- the report view -------------------------------------------------------------------------------------------------

test('the report view carries the toggle and whether its own run was blurred (the badge)', () => {
  const plain = buildReportView(smoke);
  assert.deepEqual(plain.privacy, { blurFaces: false, runBlurred: false });
  const notes = JSON.parse(smoke.modelRun.notes);
  notes.incidentConsoleV2.response.privacy = { blur_faces: true, regions: 3 };
  const blurred = buildReportView({
    ...smoke,
    video: { ...smoke.video, blur_faces: true },
    modelRun: { ...smoke.modelRun, notes: JSON.stringify(notes) },
  });
  assert.deepEqual(blurred.privacy, { blurFaces: true, runBlurred: true });
});

test('the report header shows the toggle and the Faces blurred badge only for a blurred run', () => {
  const page = readFileSync(join(process.cwd(), 'src', 'sections', 'reports', 'components', 'ReportPage', 'ReportPage.tsx'), 'utf8');
  assert.match(page, /\{report\.privacy\.runBlurred && \(\s*<Badge\s+data-testid="faces-blurred-badge"/);
  assert.match(page, /<PrivacyControls blurFaces=\{report\.privacy\.blurFaces\}/);
  const controls = readFileSync(
    join(process.cwd(), 'src', 'sections', 'reports', 'components', 'PrivacyControls', 'PrivacyControls.tsx'),
    'utf8',
  );
  assert.match(controls, /<Switch[\s\S]*?disabled=\{pending\}/, 'the toggle waits for its re-analysis');
  assert.match(controls, /setConfirm\(next\)/, 'switching asks first');
  assert.equal(privacy.privacyJobLabel({ status: 'queued' }), 'Re-analysis queued…');
  assert.equal(privacy.privacyJobLabel({ status: 'running' }), 'Re-analysing…');
});
