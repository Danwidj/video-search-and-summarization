// SPDX-License-Identifier: Apache-2.0

// One IncidentVideoRepository contract, run against the in-memory fake, the Supabase adapter over
// a fake PostgREST whose remove_video RPC mimics supabase/migrations/20261030160000_merge_remove.sql,
// and (only when P4_1_LIVE_DB=1) the Supabase adapter over the mvp3 database. The live run needs
// INCIDENT_SUPABASE_URL, INCIDENT_SUPABASE_SERVICE_ROLE_KEY and INCIDENT_MAIN_SUPABASE_URL (the
// main project's, for the equality check), refuses the frozen project, and removes only the rows
// it created (every name starts with "p4-1-").

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, describe, test } from 'node:test';

import { fakePostgrest } from './support/fake-postgrest.mjs';

register('./support/alias-loader.mjs', import.meta.url);

const { InMemoryIncidentVideoRepository } = await import('../src/modules/videos/infrastructure/memory/incident-videos.ts');
const { SupabaseIncidentVideoAdapter } = await import('../src/modules/videos/infrastructure/supabase/incident-videos.ts');
const { StoreRejection } = await import('../src/modules/shared/domain/common.ts');
const { PostgrestClient } = await import('../src/lib/postgrest/client.ts');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

const RUN = Date.now().toString(36);
const name = (label) => `p4-1-${RUN}-${label}.mp4`;

/** remove_video as the migration defines it, over the fake's tables. */
function removeVideo({ p_video_id: videoId, p_mode: mode }, store) {
  const video = store.videos.find((row) => row.id === videoId);
  if (!video) throw new Error(`video ${videoId} does not exist`);
  const incidentId = video.incident_id;
  const count = store.videos.filter((row) => row.incident_id === incidentId).length;
  let newIncidentId = null;
  let incidentDeleted = false;
  let deletedKey = null;
  if (mode === 'move') {
    if (count < 2) throw new Error(`video ${videoId} is the last video of incident ${incidentId}; delete it instead of moving it`);
    newIncidentId = Math.max(0, ...store.incidents.map((row) => row.id)) + 1;
    store.incidents.push({ id: newIncidentId });
    video.incident_id = newIncidentId;
  } else {
    deletedKey = video.filepath;
    store.videos = store.videos.filter((row) => row.id !== videoId);
    if (count < 2) {
      store.incidents = store.incidents.filter((row) => row.id !== incidentId);
      incidentDeleted = true;
    }
  }
  return {
    mode,
    video_id: videoId,
    incident_id: incidentId,
    new_incident_id: newIncidentId,
    incident_deleted: incidentDeleted,
    deleted_video_key: deletedKey,
    deleted_crop_images: [],
  };
}

const implementations = {
  memory: () => ({ repo: new InMemoryIncidentVideoRepository() }),
  'supabase (fake PostgREST)': () => {
    const db = fakePostgrest({ incidents: [], videos: [] }, { rpc: { remove_video: removeVideo }, identity: { incidents: 'id' } });
    globalThis.fetch = db.fetch;
    return { repo: new SupabaseIncidentVideoAdapter(new PostgrestClient('https://supabase.test', 'k')), db };
  },
};

const FROZEN_REF = 'rfevukimyftzbxlehwel';
const projectRef = (url) => /^https?:\/\/([^.]+)\./.exec(url ?? '')?.[1] ?? null;
const live = process.env.P4_1_LIVE_DB === '1';
if (live) {
  const ref = projectRef(process.env.INCIDENT_SUPABASE_URL);
  assert.ok(ref, 'INCIDENT_SUPABASE_URL is not set');
  assert.ok(ref !== FROZEN_REF, 'refusing to write to the frozen project');
  assert.ok(ref !== projectRef(process.env.INCIDENT_MAIN_SUPABASE_URL), 'refusing to write to the main project');
  implementations['supabase (mvp3 database)'] = () => {
    globalThis.fetch = originalFetch;
    const db = new PostgrestClient(process.env.INCIDENT_SUPABASE_URL, process.env.INCIDENT_SUPABASE_SERVICE_ROLE_KEY);
    return { repo: new SupabaseIncidentVideoAdapter(db), db, cleanup: true };
  };
}

const rejection = (reason, message) => (error) => error instanceof StoreRejection && error.reason === reason && message.test(error.message);

for (const [implementation, make] of Object.entries(implementations)) {
  describe(`IncidentVideoRepository contract: ${implementation}`, () => {
    /** Incidents this test touched, so the live run can delete exactly its own rows. */
    const incidents = new Set();
    const track = (...ids) => {
      for (const id of ids) incidents.add(id);
    };
    afterEach(async () => {
      const { db, cleanup } = current ?? {};
      if (cleanup) for (const id of incidents) await db.deleteWhere('incidents', { id: String(id) });
      incidents.clear();
    });
    let current;
    const start = () => (current = make());

    test('a video is created in a new incident by its real name and read back', async () => {
      const { repo } = start();
      const created = await repo.createVideo({
        videoId: name('a'),
        incidentId: null,
        storageKey: `uploads/${name('a')}`,
        recordedAt: '2026-10-01T08:30:00Z',
        durationSeconds: 12.4,
        source: 'sensor-1',
      });
      track(created.incidentId);
      assert.equal(created.videoId, name('a'));
      assert.equal(typeof created.incidentId, 'number');
      assert.equal(created.storageKey, `uploads/${name('a')}`);
      assert.equal(created.recordedAt, '2026-10-01T08:30:00.000Z');
      assert.equal(created.durationSeconds, 12);
      assert.equal(created.source, 'sensor-1');
      assert.deepEqual(await repo.getVideo(name('a')), { ...created, uploadedAt: (await repo.getVideo(name('a'))).uploadedAt });
      assert.equal(await repo.getVideo(name('none')), null);
    });

    test('a video without optional fields keeps them null', async () => {
      const { repo } = start();
      const created = await repo.createVideo({ videoId: name('plain'), incidentId: null, storageKey: null });
      track(created.incidentId);
      assert.deepEqual([created.storageKey, created.recordedAt, created.durationSeconds, created.source], [null, null, null, null]);
    });

    test('a second video joins the incident; unknown incidents and taken names are refused', async () => {
      const { repo } = start();
      const first = await repo.createVideo({ videoId: name('a'), incidentId: null, storageKey: 'k/a' });
      track(first.incidentId);
      const second = await repo.createVideo({ videoId: name('b'), incidentId: first.incidentId, storageKey: 'k/b' });
      assert.equal(second.incidentId, first.incidentId);
      await assert.rejects(
        repo.createVideo({ videoId: name('c'), incidentId: first.incidentId + 100000, storageKey: null }),
        rejection('not-found', /Incident not found/),
      );
      await assert.rejects(
        repo.createVideo({ videoId: name('a'), incidentId: first.incidentId, storageKey: null }),
        rejection('invalid', /already taken/),
      );
      assert.equal(await repo.getVideo(name('c')), null);
    });

    test('an incident lists its videos by recording time, unknown last, then name', async () => {
      const { repo } = start();
      const first = await repo.createVideo({
        videoId: name('late'),
        incidentId: null,
        storageKey: null,
        recordedAt: '2026-10-01T09:00:00Z',
      });
      track(first.incidentId);
      for (const [label, recordedAt] of [
        ['unknown-b', null],
        ['early', '2026-10-01T08:00:00Z'],
        ['unknown-a', null],
      ])
        await repo.createVideo({ videoId: name(label), incidentId: first.incidentId, storageKey: null, recordedAt });
      assert.deepEqual(
        (await repo.listVideos(first.incidentId)).map((video) => video.videoId),
        [name('early'), name('late'), name('unknown-a'), name('unknown-b')],
      );
      assert.deepEqual(await repo.listVideos(first.incidentId + 100000), []);
    });

    test('removing one of several videos keeps the incident and reports the key to delete', async () => {
      const { repo } = start();
      const first = await repo.createVideo({ videoId: name('a'), incidentId: null, storageKey: 'k/a' });
      track(first.incidentId);
      await repo.createVideo({ videoId: name('b'), incidentId: first.incidentId, storageKey: 'k/b' });
      const removal = await repo.removeVideo(name('a'));
      assert.deepEqual(removal, {
        videoId: name('a'),
        incidentId: first.incidentId,
        incidentDeleted: false,
        storageKey: 'k/a',
        cropImages: [],
      });
      assert.equal(await repo.getVideo(name('a')), null);
      assert.deepEqual(
        (await repo.listVideos(first.incidentId)).map((video) => video.videoId),
        [name('b')],
      );
      await assert.rejects(repo.removeVideo(name('a')), rejection('not-found', /does not exist|not found/i));
    });

    test('removing the last video deletes the emptied incident', async () => {
      const { repo } = start();
      const only = await repo.createVideo({ videoId: name('only'), incidentId: null, storageKey: 'k/only' });
      track(only.incidentId);
      const removal = await repo.removeVideo(name('only'));
      assert.equal(removal.incidentDeleted, true);
      assert.equal(removal.incidentId, only.incidentId);
      assert.equal(removal.storageKey, 'k/only');
      await assert.rejects(
        repo.createVideo({ videoId: name('again'), incidentId: only.incidentId, storageKey: null }),
        rejection('not-found', /Incident not found/),
      );
    });

    test('a moved video gets an incident of its own and the old one keeps the rest', async () => {
      const { repo } = start();
      const first = await repo.createVideo({ videoId: name('a'), incidentId: null, storageKey: 'k/a', recordedAt: '2026-10-01T08:00:00Z' });
      track(first.incidentId);
      await repo.createVideo({ videoId: name('b'), incidentId: first.incidentId, storageKey: 'k/b' });
      const move = await repo.moveVideoToNewIncident(name('b'));
      track(move.newIncidentId);
      assert.equal(move.incidentId, first.incidentId);
      assert.notEqual(move.newIncidentId, first.incidentId);
      const moved = await repo.getVideo(name('b'));
      assert.equal(moved.incidentId, move.newIncidentId);
      assert.equal(moved.storageKey, 'k/b');
      assert.deepEqual(
        (await repo.listVideos(first.incidentId)).map((video) => video.videoId),
        [name('a')],
      );
      assert.deepEqual(
        (await repo.listVideos(move.newIncidentId)).map((video) => video.videoId),
        [name('b')],
      );
    });

    test('moving the last video or an unknown one is refused', async () => {
      const { repo } = start();
      const only = await repo.createVideo({ videoId: name('only'), incidentId: null, storageKey: null });
      track(only.incidentId);
      await assert.rejects(repo.moveVideoToNewIncident(name('only')), rejection('invalid', /last video/));
      assert.equal((await repo.getVideo(name('only'))).incidentId, only.incidentId);
      await assert.rejects(repo.moveVideoToNewIncident(name('none')), rejection('not-found', /does not exist|not found/i));
    });
  });
}

describe('SupabaseIncidentVideoAdapter', () => {
  test('creating in a new incident posts the incident, then the video with its columns', async () => {
    const { repo, db } = implementations['supabase (fake PostgREST)']();
    await repo.createVideo({
      videoId: 'a.mp4',
      incidentId: null,
      storageKey: 'k/a',
      recordedAt: '2026-10-01T08:30:00+08:00',
      durationSeconds: 3.6,
    });
    assert.deepEqual(
      db.requests.filter((request) => request.method === 'POST'),
      [
        { method: 'POST', path: 'incidents', body: {} },
        {
          method: 'POST',
          path: 'videos',
          body: {
            id: 'a.mp4',
            incident_id: 1,
            filepath: 'k/a',
            recorded_at: '2026-10-01T00:30:00.000Z',
            duration: 4,
            source: null,
          },
        },
      ],
    );
  });

  test('removing and moving are one remove_video call each with the mode', async () => {
    const { repo, db } = implementations['supabase (fake PostgREST)']();
    const first = await repo.createVideo({ videoId: 'a.mp4', incidentId: null, storageKey: null });
    await repo.createVideo({ videoId: 'b.mp4', incidentId: first.incidentId, storageKey: null });
    await repo.moveVideoToNewIncident('b.mp4');
    await repo.removeVideo('a.mp4');
    assert.deepEqual(
      db.requests.filter((request) => request.path === 'rpc/remove_video').map((request) => request.body),
      [
        { p_video_id: 'b.mp4', p_mode: 'move' },
        { p_video_id: 'a.mp4', p_mode: 'delete' },
      ],
    );
  });

  test('other PostgREST failures are not turned into rejections', async () => {
    globalThis.fetch = async () => new Response('{"message":"permission denied"}', { status: 401 });
    const repo = new SupabaseIncidentVideoAdapter(new PostgrestClient('https://supabase.test', 'k'));
    await assert.rejects(repo.removeVideo('a.mp4'), (error) => !(error instanceof StoreRejection) && /HTTP 401/.test(error.message));
  });
});
