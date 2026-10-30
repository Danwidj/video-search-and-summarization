// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

import { getStageAnnouncement, getStageProgress, stageLabels, stageOrder } from '../src/sections/analysis/stage-progress.ts';

test('analysis stages list has exactly 5 stages with proper sequential order and labels', () => {
  assert.equal(stageLabels.length, 5);
  assert.deepEqual(
    stageLabels.map((s) => s.key),
    ['uploading', 'preparing', 'analyzing', 'saving', 'complete'],
  );
  assert.equal(stageOrder.uploading, 0);
  assert.equal(stageOrder.preparing, 1);
  assert.equal(stageOrder.analyzing, 2);
  assert.equal(stageOrder.saving, 3);
  assert.equal(stageOrder.complete, 4);
});

test('getStageProgress computes smooth and accurate progress across stages', () => {
  assert.equal(getStageProgress('idle'), 0);
  assert.equal(getStageProgress('uploading', 0), 2);
  assert.equal(getStageProgress('uploading', 50), 10);
  assert.equal(getStageProgress('uploading', 100), 20);
  assert.equal(getStageProgress('preparing'), 40);
  assert.equal(getStageProgress('analyzing'), 60);
  assert.equal(getStageProgress('saving'), 80);
  assert.equal(getStageProgress('complete'), 100);

  // When in error state, progress retains the failed stage progress
  assert.equal(getStageProgress('error', 0, 'analyzing'), 60);
  assert.equal(getStageProgress('error', 0, 'uploading'), 2);
  assert.equal(getStageProgress('error', 0, 'idle'), 0);
});

test('getStageAnnouncement generates clear accessible announcements for screen readers', () => {
  assert.match(getStageAnnouncement('uploading', 45), /Stage 1 of 5: Uploading video \(45%\)\./);
  assert.equal(getStageAnnouncement('preparing'), 'Stage 2 of 5: Preparing secure access.');
  assert.equal(getStageAnnouncement('analyzing'), 'Stage 3 of 5: Understanding the incident.');
  assert.equal(getStageAnnouncement('saving'), 'Stage 4 of 5: Structuring and saving report.');
  assert.equal(getStageAnnouncement('complete'), 'Stage 5 of 5: Report ready. Analysis complete.');
  assert.equal(getStageAnnouncement('error', 0, 'Gateway timed out'), 'Analysis failed: Gateway timed out');
});

test('the batch workspace uses shadcn Progress and accessible ARIA attributes', async () => {
  const workspace = await readFile(
    new URL('../src/sections/analysis/components/AnalysisWorkspace/AnalysisWorkspace.tsx', import.meta.url),
    'utf8',
  );
  const row = await readFile(new URL('../src/sections/analysis/components/BatchFileRow/BatchFileRow.tsx', import.meta.url), 'utf8');

  // Verify shadcn Progress import and usage for the batch and for each file
  assert.match(workspace, /import\s+\{\s*Progress\s*\}\s+from\s+'@\/components\/ui\/progress'/);
  assert.match(workspace, /<Progress\b/);
  assert.match(workspace, /aria-label="Batch progress"/);
  assert.match(workspace, /aria-valuetext=\{announcement\}/);
  assert.match(row, /import\s+\{\s*Progress\s*\}\s+from\s+'@\/components\/ui\/progress'/);
  assert.match(row, /aria-label=\{`Progress for \$\{item\.name\}`\}/);

  // Verify screen reader live region announcement
  assert.match(workspace, /role="status"/);
  assert.match(workspace, /aria-live="polite"/);

  // Verify each file's stage list beneath its progress bar
  assert.match(row, /aria-label=\{`Stages for \$\{item\.name\}`\}/);
  assert.match(row, /aria-current=\{active \? 'step' : undefined\}/);
  assert.match(row, /\(completed\)/);
  assert.match(row, /\(current step\)/);
  assert.match(row, /\(failed\)/);
});
