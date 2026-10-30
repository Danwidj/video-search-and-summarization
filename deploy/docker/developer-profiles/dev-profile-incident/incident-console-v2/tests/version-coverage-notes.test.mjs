// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { coverageNoteLines } = await import('../src/lib/reports/coverage-notes.ts');
const { layoutVersions } = await import('../src/lib/reports/version-graph.ts');
const { coverageVerdict, coverageNote } = await import('../src/modules/reports/domain/envelope.ts');
const { markOfficial, clearOfficial } = await import('../src/lib/reports/official-client.ts');

test('a complete version has no coverage note', () => {
  assert.deepEqual(coverageNoteLines(coverageVerdict(['a.mp4', 'b.mp4'], ['b.mp4', 'a.mp4'])), []);
  assert.deepEqual(coverageNoteLines(undefined), []);
});

test('a version built before a video was added says what it does not include', () => {
  assert.deepEqual(coverageNoteLines(coverageVerdict(['a.mp4'], ['a.mp4', 'b.mp4', 'c.mp4'])), [
    { kind: 'gap', text: 'Does not include: b.mp4, c.mp4' },
  ]);
});

test('a version that still holds a removed video says so', () => {
  assert.deepEqual(coverageNoteLines(coverageVerdict(['a.mp4', 'gone.mp4'], ['a.mp4'])), [
    { kind: 'removed', text: 'Includes a removed video: gone.mp4' },
  ]);
});

test('both notes show together and read like the route note', () => {
  const verdict = coverageVerdict(['gone.mp4'], ['new.mp4']);
  const lines = coverageNoteLines(verdict);
  assert.deepEqual(
    lines.map((line) => line.kind),
    ['gap', 'removed'],
  );
  assert.equal(lines.map((line) => line.text).join('. '), coverageNote(verdict));
});

test('the version graph keeps the extra fields of each row, such as coverage', () => {
  const rows = [
    { revisionId: 12, revisionNo: 2, parentId: null, coverage: { verdict: { status: 'complete' }, note: null } },
    { revisionId: 11, revisionNo: 1, parentId: null, coverage: { verdict: { status: 'lacks', missing: ['b.mp4'] }, note: 'Does not include: b.mp4' } },
  ];
  const { rows: laid } = layoutVersions(rows);
  assert.equal(laid[1].revision.coverage.note, 'Does not include: b.mp4');
});

test('official controls call the incident route with the incident id', async () => {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push([url, init.method, init.body ?? null]);
    return new Response('{}', { status: 200 });
  };
  try {
    await markOfficial('42', 7);
    await clearOfficial('42');
  } finally {
    globalThis.fetch = original;
  }
  assert.deepEqual(calls, [
    ['/api/videos/42/official', 'PUT', '{"revisionId":7}'],
    ['/api/videos/42/official', 'DELETE', null],
  ]);
});
