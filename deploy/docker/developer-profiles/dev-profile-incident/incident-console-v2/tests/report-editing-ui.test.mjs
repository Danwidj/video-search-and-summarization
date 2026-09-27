// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const components = new URL('../components/', import.meta.url);

test('report page separates structured fields, read-only model output and run details', async () => {
  const report = await readFile(new URL('incident-report.tsx', components), 'utf8');

  assert.match(report, /Model severity rationale/);
  assert.match(report, /reviewer set/, 'an edited severity is shown against the model severity');
  assert.match(report, /Model event timeline/);
  assert.match(report, /Model-reported uncertainties/);
  assert.match(report, /Original model output · read-only/);
  assert.match(report, /Run &amp; model output details/);
  assert.match(report, /Additional instruction/);
  assert.match(report, /Prompt SHA-256/);
  assert.match(report, /Contract repair applied \(IDs only\)/);
  assert.match(report, /Repair operations/);
  assert.match(report, /First-pass violations/);
  assert.match(report, /Valid after structural repair/);
  assert.match(report, /confidenceScore !== null/, 'no confidence percentage when the model returned none');
  assert.doesNotMatch(report, /<input|<textarea/, 'the report view itself has no inputs; editing happens in the structured editor');
  assert.match(report, /StructuredEditor/);
  assert.match(report, /Model classified this as/);
  assert.match(report, /model window/);
  assert.match(report, /last edited by/);
});

test('library cards omit the confidence percentage when the model returned none', async () => {
  const library = await readFile(new URL('reports-library.tsx', components), 'utf8');
  assert.match(library, /item\.confidence !== null && <span/);
});

test('browser components import only browser-safe report modules', async () => {
  const serverOnly = [/@\/lib\/reports\/view'/, /@\/lib\/reports\/run-notes'/, /@\/lib\/contract\/(load|validate)'/, /@\/lib\/analysis\/(persistence|run-contract-analysis|build-request)'/, /from 'node:/];
  const clientOnly = await readFile(new URL('../lib/reports/report-view.ts', import.meta.url), 'utf8');
  for (const name of ['incident-report.tsx', 'structured-editor.tsx', 'report-screen.tsx', 'run-comparison.tsx', 'advanced-report-tools.tsx', 'reports-library.tsx', 'analysis-workspace.tsx']) {
    const source = await readFile(new URL(name, components), 'utf8');
    for (const pattern of serverOnly) assert.doesNotMatch(source, pattern, `${name} must not import ${pattern}`);
  }
  for (const line of clientOnly.split('\n').filter((l) => l.startsWith('import '))) {
    assert.match(line, /^import type /, `lib/reports/report-view.ts may only import types: ${line}`);
  }
});

test('the structured editor edits Class A only and shows the original model output read-only', async () => {
  const editor = await readFile(new URL('structured-editor.tsx', components), 'utf8');
  assert.match(editor, /Original model output · read-only/);
  assert.match(editor, /Model severity rationale/);
  for (const classB of ['severity_reason', 'title:', 'location:', 'uncertainties:', 'timeline:']) {
    assert.ok(!new RegExp(`setIncident\\(\\{ ${classB.replace(':', '')}`).test(editor), `${classB} must not be editable`);
  }
  assert.match(editor, /editFromDraft/);
});
