// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { register } from 'node:module';
import { join } from 'node:path';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

await import('../src/modules/contract/infrastructure/loader.ts');
const envelope = await import('../src/modules/reports/domain/envelope.ts');

const validReport = JSON.parse(readFileSync(join(process.cwd(), '..', 'contracts', 'fixtures', 'valid', 'minimal-report.json'), 'utf8'));
const clone = (value) => JSON.parse(JSON.stringify(value));

const stored = () => ({
  overview: { title: ' Fight ', type: 'fighting', severity_level: 3, description: 'd', location: '' },
  cameras: [
    { video: 'front.mp4', report: clone(validReport) },
    { video: 'back.mp4', report: { incident: 'broken' } },
    { video: 'front.mp4', report: {} },
    { video: '', report: {} },
  ],
});

test('parseEnvelope normalises the overview and drops nameless and repeated cameras', () => {
  const parsed = envelope.parseEnvelope(stored());
  assert.deepEqual(parsed.overview, { title: 'Fight', type: 'assault', severity_level: 3, description: 'd', location: null });
  assert.deepEqual(envelope.cameraNames(parsed), ['front.mp4', 'back.mp4']);
});

test('parseEnvelope reads junk as an empty envelope', () => {
  for (const junk of [null, 'x', [], {}, { cameras: 'no' }]) {
    const parsed = envelope.parseEnvelope(junk);
    assert.deepEqual(parsed.cameras, []);
    assert.deepEqual(parsed.overview, { title: null, type: null, severity_level: null, description: null, location: null });
  }
  assert.equal(envelope.normaliseOverview({ severity_level: 9 }).severity_level, null);
});

test('envelopePayload round-trips through parseEnvelope', () => {
  const parsed = envelope.parseEnvelope(stored());
  assert.deepEqual(envelope.parseEnvelope(envelope.envelopePayload(parsed)), parsed);
});

test('cameraReport returns only a contract-valid report', () => {
  const parsed = envelope.parseEnvelope(stored());
  assert.deepEqual(envelope.cameraReport(parsed, 'front.mp4'), validReport);
  assert.equal(envelope.cameraReport(parsed, 'back.mp4'), null);
  assert.equal(envelope.cameraReport(parsed, 'missing.mp4'), null);
});

test('firstValidCamera skips invalid cameras and honours the preferred names', () => {
  const parsed = envelope.parseEnvelope(stored());
  assert.equal(envelope.firstValidCamera(parsed), 'front.mp4');
  assert.equal(envelope.firstValidCamera(parsed, ['back.mp4']), null);
  assert.equal(envelope.firstValidCamera(parsed, ['back.mp4', 'front.mp4']), 'front.mp4');
});

test('replaceCameraReport changes one camera and leaves the rest and the input alone', () => {
  const parsed = envelope.parseEnvelope(stored());
  const before = clone(parsed);
  const next = envelope.replaceCameraReport(parsed, 'back.mp4', clone(validReport));
  assert.deepEqual(parsed, before);
  assert.deepEqual(next.overview, parsed.overview);
  assert.deepEqual(next.cameras[0], parsed.cameras[0]);
  assert.deepEqual(envelope.cameraReport(next, 'back.mp4'), validReport);
  assert.throws(() => envelope.replaceCameraReport(parsed, 'nope.mp4', {}), /no camera for nope\.mp4/);
});

test('replaceOverview changes only the overview', () => {
  const parsed = envelope.parseEnvelope(stored());
  const next = envelope.replaceOverview(parsed, { title: 'New', type: 'burglary', severity_level: 5 });
  assert.deepEqual(next.overview, { title: 'New', type: 'burglary', severity_level: 5, description: null, location: null });
  assert.deepEqual(next.cameras, parsed.cameras);
});

test('coverageVerdict: complete, lacks, removed and both', () => {
  assert.deepEqual(envelope.coverageVerdict(['a', 'b'], ['b', 'a']), { status: 'complete' });
  assert.deepEqual(envelope.coverageVerdict(['a'], ['a', 'b', 'b']), { status: 'lacks', missing: ['b'] });
  assert.deepEqual(envelope.coverageVerdict(['a', 'gone'], ['a']), { status: 'removed', removed: ['gone'] });
  assert.deepEqual(envelope.coverageVerdict(['gone'], ['a']), { status: 'lacks-and-removed', missing: ['a'], removed: ['gone'] });
  assert.deepEqual(envelope.coverageVerdict([], []), { status: 'complete' });
});

test('coverageNote words match the plan', () => {
  assert.equal(envelope.coverageNote({ status: 'complete' }), null);
  assert.equal(envelope.coverageNote({ status: 'lacks', missing: ['a.mp4', 'b.mp4'] }), 'Does not include: a.mp4, b.mp4');
  assert.equal(envelope.coverageNote({ status: 'removed', removed: ['x.mp4'] }), 'Includes a removed video: x.mp4');
  assert.equal(
    envelope.coverageNote({ status: 'lacks-and-removed', missing: ['a'], removed: ['x'] }),
    'Does not include: a. Includes a removed video: x',
  );
});

const grouped = () => ({
  ...stored(),
  evidence_groups: [
    {
      id: 'G1',
      kind: 'entity',
      label: 'Man in blue shirt',
      members: [
        { video: 'front.mp4', itemId: 'E1' },
        { video: 'back.mp4', itemId: 'E2' },
      ],
      source: 'ai',
      reason: 'Same shirt.',
    },
  ],
});

test('evidence_groups survive parse and envelopePayload, and old payloads have none', () => {
  const parsed = envelope.parseEnvelope(grouped());
  assert.equal(parsed.evidenceGroups.length, 1);
  assert.deepEqual(envelope.envelopePayload(parsed).evidence_groups, grouped().evidence_groups);
  const plain = envelope.parseEnvelope(stored());
  assert.equal('evidenceGroups' in plain, false);
  assert.equal('evidence_groups' in envelope.envelopePayload(plain), false);
  // an edit of one camera or the overview keeps the groups
  const edited = envelope.replaceOverview(parsed, { title: 'New' });
  assert.equal(envelope.envelopePayload(edited).evidence_groups.length, 1);
});

test('parseEvidenceGroups drops groups that break the rules and keeps the rest', () => {
  const member = (video, itemId) => ({ video, itemId });
  const ok = { id: 'G1', kind: 'asset', label: 'Bag', members: [member('a', 'A1'), member('b', 'A1')], source: 'human' };
  const groups = envelope.parseEvidenceGroups([
    ok,
    { ...ok, id: 'G2', members: [member('a', 'A1'), member('c', 'A1')] }, // reuses (a, A1)
    { ...ok, id: 'G3', members: [member('a', 'A2'), member('a', 'A3')] }, // one video twice
    { ...ok, id: 'G4', members: [member('a', 'A2')] }, // one member
    { ...ok, id: 'G5', kind: 'person', members: [member('a', 'A2'), member('b', 'A2')] },
    { ...ok, id: 'G6', source: 'robot', members: [member('a', 'A2'), member('b', 'A2')] },
    { ...ok, id: 'G7', members: [member('a', 'A2'), { video: 'b' }] },
    null,
  ]);
  assert.deepEqual(
    groups.map((group) => group.id),
    ['G1'],
  );
  assert.deepEqual(envelope.parseEvidenceGroups('x'), []);
});
