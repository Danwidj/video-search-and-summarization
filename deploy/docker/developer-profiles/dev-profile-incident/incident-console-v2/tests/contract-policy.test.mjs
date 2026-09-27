// SPDX-License-Identifier: Apache-2.0

// Validation policy core-scored-v1 in the console validator, and the MP4 length
// reader it depends on. contracts/fixtures/policy/ is shared with
// eval/tests/test_contract_fixtures.py, so Python and TypeScript must agree on
// every recorded response and boundary case.

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { ContractError, decodeContent, validateCore, validateReport, violationScope, timestampWithinVideo, VALIDATION_POLICY } = await import('../lib/contract/validate.ts');
const { mp4DurationSeconds } = await import('../lib/video/mp4-duration.ts');

const policyDir = join(process.cwd(), '..', 'contracts', 'fixtures', 'policy');
const cases = readdirSync(policyDir).filter((name) => name.endsWith('.json')).sort();

/** The TypeScript verdict in the fixture's terms. */
function verdict(content, videoDurationSeconds) {
  let decoded;
  try {
    decoded = decodeContent(content);
  } catch (error) {
    return { fullContractOk: false, coreOk: false, core: error.violations.map((v) => v.code), enrichment: [] };
  }
  let fullContractOk = true;
  try {
    validateReport(decoded);
  } catch {
    fullContractOk = false;
  }
  try {
    const result = validateCore(decoded, { videoDurationSeconds });
    assert.equal(result.fullContractValid, fullContractOk);
    return { fullContractOk, coreOk: true, core: [], enrichment: result.enrichment.map((v) => v.code), videoBoundsChecked: result.videoBoundsChecked };
  } catch (error) {
    assert.ok(error instanceof ContractError);
    const scoped = (scope) => error.violations.filter((v) => violationScope(v.code) === scope).map((v) => v.code);
    return { fullContractOk, coreOk: false, core: scoped('core'), enrichment: scoped('enrichment') };
  }
}

const unique = (codes) => [...new Set(codes)].sort();

test('the shared policy fixtures exist', () => {
  assert.ok(cases.length >= 20);
  assert.equal(VALIDATION_POLICY, 'core-scored-v1');
});

for (const name of cases) {
  test(`policy fixture: ${name}`, () => {
    const fixture = JSON.parse(readFileSync(join(policyDir, name), 'utf8'));
    const result = verdict(fixture.content, fixture.video_duration_seconds);
    assert.equal(result.fullContractOk, fixture.expected.full_contract_ok, 'full contract validity');
    assert.equal(result.coreOk, fixture.expected.core_ok, 'core validity');
    assert.deepEqual(unique(result.core), fixture.expected.core_codes);
    assert.deepEqual(unique(result.enrichment), fixture.expected.enrichment_codes);
    if (result.coreOk) assert.equal(result.videoBoundsChecked, fixture.video_duration_seconds !== null);
  });
}

test('a core-valid report is returned exactly as the model sent it (no repair, clipping or removal)', () => {
  const fixture = JSON.parse(readFileSync(join(policyDir, 'real-assault018-cosmos-super-prompt-a.json'), 'utf8'));
  const result = validateCore(decodeContent(fixture.content), { videoDurationSeconds: fixture.video_duration_seconds });
  assert.deepEqual(result.report, JSON.parse(fixture.content));
});

test('whole-second video bounds: T is within a D-second video iff 0 <= T < D + 1', () => {
  for (const [duration, accepted, rejected] of [[12.54, 13, 14], [22, 22, 23], [22.83, 23, 24]]) {
    assert.ok(timestampWithinVideo(accepted, duration), `${accepted} within ${duration}`);
    assert.ok(!timestampWithinVideo(rejected, duration), `${rejected} beyond ${duration}`);
  }
  assert.ok(!timestampWithinVideo(-1, 10));
});

test('scopes: only timeline problems are enrichment; everything else is core', () => {
  for (const code of ['TIMELINE_START_OUTSIDE_WINDOW', 'TIMELINE_END_OUTSIDE_WINDOW', 'TIMELINE_NOT_CHRONOLOGICAL', 'TIMELINE_BEYOND_VIDEO']) assert.equal(violationScope(code), 'enrichment');
  for (const code of ['EMPTY_CONTENT', 'INVALID_JSON', 'SCHEMA_VIOLATION', 'WINDOW_END_BEFORE_START', 'WINDOW_BEYOND_VIDEO', 'ID_NOT_SEQUENTIAL_ENTITY', 'INSTRUMENT_HOLDER_UNKNOWN']) assert.equal(violationScope(code), 'core');
});

// --- MP4 length ---------------------------------------------------------------

function box(type, body) {
  const out = Buffer.alloc(8 + body.length);
  out.writeUInt32BE(8 + body.length, 0);
  out.write(type, 4, 'latin1');
  body.copy(out, 8);
  return out;
}

function mvhd(timescale, duration, version = 0) {
  if (version === 1) {
    const body = Buffer.alloc(4 + 16 + 12 + 80);
    body[0] = 1;
    body.writeUInt32BE(timescale, 20);
    body.writeBigUInt64BE(BigInt(duration), 24);
    return box('mvhd', body);
  }
  const body = Buffer.alloc(4 + 8 + 8 + 80);
  body.writeUInt32BE(timescale, 12);
  body.writeUInt32BE(duration, 16);
  return box('mvhd', body);
}

function reader(bytes, calls) {
  return async (offset, length) => {
    calls?.push([offset, length]);
    return new Uint8Array(bytes.subarray(offset, offset + length));
  };
}

test('MP4 length with moov after mdat: only box headers and moov are read', async () => {
  const bytes = Buffer.concat([box('ftyp', Buffer.alloc(16)), box('mdat', Buffer.alloc(500_000)), box('moov', Buffer.concat([box('trak', Buffer.alloc(24)), mvhd(1000, 12539)]))]);
  const calls = [];
  assert.equal(await mp4DurationSeconds(reader(bytes, calls), bytes.length), 12.539);
  assert.ok(calls.reduce((sum, [, length]) => sum + length, 0) < 2_000, 'the media data is skipped, never read');
});

test('MP4 length from a version-1 mvhd and a 64-bit box size', async () => {
  const mdat = Buffer.alloc(16 + 100);
  mdat.writeUInt32BE(1, 0);
  mdat.write('mdat', 4, 'latin1');
  mdat.writeBigUInt64BE(116n, 8);
  const bytes = Buffer.concat([box('ftyp', Buffer.alloc(8)), mdat, box('moov', mvhd(600, 13_700, 1))]);
  assert.equal(await mp4DurationSeconds(reader(bytes), bytes.length), 13_700 / 600);
});

test('MP4 length is unknown (null) whenever the header cannot be read', async () => {
  const runsPastEnd = Buffer.alloc(18);
  runsPastEnd.writeUInt32BE(4000, 0);
  runsPastEnd.write('mdat', 4, 'latin1');
  for (const bytes of [
    Buffer.alloc(0),
    Buffer.from('not an mp4 file at all'),
    Buffer.concat([box('ftyp', Buffer.alloc(8)), box('mdat', Buffer.alloc(64))]),
    box('moov', box('trak', Buffer.alloc(8))),
    box('moov', mvhd(0, 100)),
    runsPastEnd,
  ]) {
    assert.equal(await mp4DurationSeconds(reader(bytes), bytes.length), null);
  }
  const failing = async () => { throw new Error('R2 read failed'); };
  assert.equal(await mp4DurationSeconds(failing, 1000), null);
});
