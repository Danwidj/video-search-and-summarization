// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const components = new URL('../components/', import.meta.url);

test('report page separates structured fields, read-only model output and run details', async () => {
  const report = (await Promise.all(['report-pane.tsx', 'report-run-details.tsx', 'report-page.tsx'].map((name) => readFile(new URL(name, components), 'utf8')))).join('\n');

  assert.match(report, /Severity rationale/);
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
  assert.doesNotMatch(report, /createdBy/, 'human versions show no author name');
  assert.match(report, /StructuredEditor/);
  assert.match(report, /Model classified this as/);
  assert.match(report, /model window/);
  assert.match(report, /not consistent with the detected incident window/, 'an inconsistent timeline is labelled as such');
  assert.match(report, /outside incident window/);
  assert.match(report, /outside the video/);
  assert.match(report, /event\.seekable !== false && \(playerDuration === null \|\| timestampWithinVideo\(/, 'seeking is blocked only for a time outside the video');
  assert.match(report, /Validation policy/);
  assert.match(report, /Full contract validity \(first response\)/);
});

test('the report page has a History of versions, a reviewer prompt and explicit official controls, and no verification flow', async () => {
  const report = await readFile(new URL('report-page.tsx', components), 'utf8');
  assert.match(report, /ReportVersions/);
  const history = await readFile(new URL('report-versions.tsx', components), 'utf8');
  assert.match(history, /markOfficial/);
  assert.match(history, /role="alert"/, 'the agent-unreachable message is shown inline');
  assert.doesNotMatch(history, /restore/i);
  const reanalysis = await readFile(new URL('reanalysis-card.tsx', components), 'utf8');
  assert.match(reanalysis, /Reviewer prompt \(optional\)/);
  assert.match(reanalysis, /additionalInstruction/);
  for (const name of ['report-page.tsx', 'report-pane.tsx', 'report-timeline.tsx', 'advanced-report-tools.tsx', 'structured-editor.tsx', 'report-versions.tsx', 'official-controls.tsx', 'library/library-screen.tsx', 'library/incident-card.tsx']) {
    const source = await readFile(new URL(name, components), 'utf8');
    assert.doesNotMatch(source, /Unverify|under review|api\/reports\/[^'`]*\/review|review_status|reviewStatus/, `${name} has no verification flow`);
  }
});

test('library incident cards show no confidence percentage', async () => {
  const card = await readFile(new URL('library/incident-card.tsx', components), 'utf8');
  assert.doesNotMatch(card, /confidence/);
});

test('browser components import only browser-safe report modules', async () => {
  const serverOnly = [/@\/lib\/reports\/view'/, /@\/lib\/reports\/run-notes'/, /@\/lib\/contract\/(load|validate)'/, /@\/lib\/analysis\/(persistence|run-contract-analysis|build-request)'/, /from 'node:/];
  const clientOnly = await readFile(new URL('../lib/reports/report-view.ts', import.meta.url), 'utf8');
  for (const name of ['report-page.tsx', 'report-pane.tsx', 'report-timeline.tsx', 'report-versions.tsx', 'report-run-details.tsx', 'structured-editor.tsx', 'run-history.tsx', 'reanalysis-card.tsx', 'video-history-screen.tsx', 'videos-screen.tsx', 'run-comparison.tsx', 'advanced-report-tools.tsx', 'analysis-workspace.tsx', 'library/library-screen.tsx', 'library/incident-card.tsx']) {
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

test('the report page offers re-analysis and history', async () => {
  const tools = await readFile(new URL('advanced-report-tools.tsx', components), 'utf8');
  assert.match(tools, /ReanalysisCard/);
  assert.match(tools, /RunHistoryList/);
  const library = await readFile(new URL('library/library-screen.tsx', components), 'utf8');
  assert.doesNotMatch(library, /\/api\/analysis/, 'the library no longer re-runs with the default model');
  assert.match(await readFile(new URL('library/incident-card.tsx', components), 'utf8'), /library-repair-marker/);
  const history = await readFile(new URL('run-history.tsx', components), 'utf8');
  assert.match(history, /no report/);
  assert.match(history, /Contract violations/);
});

test('no component renders stored timestamps with a bare new Date(...).toLocaleString()', async () => {
  for (const name of ['report-pane.tsx', 'report-versions.tsx', 'run-comparison.tsx', 'run-history.tsx', 'video-history-screen.tsx', 'videos-screen.tsx', 'advanced-report-tools.tsx', 'library/library-screen.tsx', 'library/incident-card.tsx', 'library/hit-card.tsx']) {
    const source = await readFile(new URL(name, components), 'utf8');
    assert.doesNotMatch(source, /new Date\([^)]*\)\.toLocale/, name);
  }
});

test('the new-analysis model selector shows full model names and never clips them', async () => {
  const workspace = await readFile(new URL('analysis-workspace.tsx', components), 'utf8');
  const select = /<select className="([^"]*)"[^>]*id="analysis-model"/.exec(workspace);
  assert.ok(select, 'the model selector exists');
  const classes = select[1].split(/\s+/);
  for (const needed of ['sm:w-auto', 'sm:min-w-[19rem]', 'sm:shrink-0']) assert.ok(classes.includes(needed), `select has ${needed}`);
  assert.ok(!classes.some((name) => /max-w-/.test(name)), 'no max width that would clip a model name');
  assert.match(workspace, /<option key=\{option\.id\} value=\{option\.id\}>\{option\.label\}<\/option>/, 'options show the full friendly label and keep the model id as value');
  assert.match(workspace, /sm:flex-wrap/, 'on narrow rows the note wraps instead of squeezing the selector');

  const inference = JSON.parse(await readFile(new URL('../../contracts/inference.json', import.meta.url), 'utf8'));
  assert.deepEqual(inference.models.map((model) => model.label), ['Cosmos 3 Nano Reasoner', 'Cosmos 3 Super Reasoner', 'Nemotron 3 Nano Omni Reasoning']);
});
