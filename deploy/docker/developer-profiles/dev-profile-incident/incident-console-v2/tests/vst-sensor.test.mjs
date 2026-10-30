// SPDX-License-Identifier: Apache-2.0

// The VST sensor adapter against a fake VST: exact sensor only, a missing sensor counts as removed.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { afterEach, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { removeVstSensor, vstSensorName } = await import('../src/modules/videos/infrastructure/vst/sensor.ts');

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

/** A fake VST holding `sensors`; `deleteStatus` forces the answer to a sensor delete. */
function fakeVst(sensors, { deleteStatus = null } = {}) {
  const calls = [];
  globalThis.fetch = async (input, init) => {
    const method = init?.method ?? 'GET';
    calls.push(`${method} ${String(input)}`);
    if (method === 'GET') return Response.json(sensors);
    const id = String(input).split('/').pop();
    if (deleteStatus) return new Response('refused', { status: deleteStatus });
    const found = sensors.some((sensor) => sensor.sensorId === id);
    return new Response(null, { status: found ? 204 : 404 });
  };
  return calls;
}

const config = { vstUrl: 'http://vst.test/', agentUrl: 'http://agent.test' };

test('the sensor name is the file name without its extension', () => {
  assert.equal(vstSensorName('IMG_9170_480.mp4'), 'IMG_9170_480');
  assert.equal(vstSensorName('a.b.mov'), 'a.b');
  assert.equal(vstSensorName('noext'), 'noext');
});

test('a stored sensor id is deleted directly, with no list and no name matching', async () => {
  const calls = fakeVst([{ sensorId: 's1', name: 'a' }]);
  await removeVstSensor(config, { videoId: 'a.mp4', sensorId: 's1' });
  assert.deepEqual(calls, ['DELETE http://vst.test/vst/api/v1/sensor/s1']);
});

test('a missing sensor id is resolved by the exact name, then only that sensor is deleted', async () => {
  const calls = fakeVst([
    { sensorId: 's1', name: 'a' },
    { sensorId: 's2', name: 'a_2' },
    { sensorId: 's3', name: 'A' },
  ]);
  await removeVstSensor(config, { videoId: 'a.mp4', sensorId: null });
  assert.deepEqual(calls, ['GET http://vst.test/vst/api/v1/sensor/list', 'DELETE http://vst.test/vst/api/v1/sensor/s1']);
});

test('no sensor of that name deletes nothing; two of that name refuse to guess', async () => {
  let calls = fakeVst([{ sensorId: 's2', name: 'other' }]);
  await removeVstSensor(config, { videoId: 'a.mp4', sensorId: null });
  assert.deepEqual(calls, ['GET http://vst.test/vst/api/v1/sensor/list']);
  calls = fakeVst([
    { sensorId: 's1', name: 'a' },
    { sensorId: 's2', name: 'a' },
  ]);
  await assert.rejects(removeVstSensor(config, { videoId: 'a.mp4', sensorId: null }), /2 sensors named a/);
  assert.deepEqual(calls, ['GET http://vst.test/vst/api/v1/sensor/list']);
});

test('a sensor VST no longer has counts as removed; any other refusal throws', async () => {
  fakeVst([]);
  await removeVstSensor(config, { videoId: 'a.mp4', sensorId: 'gone' });
  fakeVst([{ sensorId: 's1', name: 'a' }], { deleteStatus: 503 });
  await assert.rejects(removeVstSensor(config, { videoId: 'a.mp4', sensorId: 's1' }), /HTTP 503: refused/);
});

test('the agent URL serves VST when no VST URL is set, and no URL at all throws', async () => {
  const calls = fakeVst([{ sensorId: 's1', name: 'a' }]);
  await removeVstSensor({ agentUrl: 'http://agent.test' }, { videoId: 'a.mp4', sensorId: 's1' });
  assert.deepEqual(calls, ['DELETE http://agent.test/vst/api/v1/sensor/s1']);
  await assert.rejects(removeVstSensor({}, { videoId: 'a.mp4', sensorId: 's1' }), /INCIDENT_VST_BASE_URL is not configured/);
});
