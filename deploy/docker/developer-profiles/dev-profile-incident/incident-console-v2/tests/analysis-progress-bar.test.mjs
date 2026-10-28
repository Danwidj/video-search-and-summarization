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

test('AnalysisWorkspace component uses shadcn Progress and accessible ARIA attributes', async () => {
  const filePath = new URL('../src/sections/analysis/components/AnalysisWorkspace/AnalysisWorkspace.tsx', import.meta.url);
  const source = await readFile(filePath, 'utf8');

  // Verify shadcn Progress import and usage
  assert.match(source, /import\s+\{\s*Progress\s*\}\s+from\s+'@\/components\/ui\/progress'/);
  assert.match(source, /<Progress\b/);
  assert.match(source, /aria-label="Analysis progress"/);
  assert.match(source, /aria-valuenow=\{progressValue\}/);
  assert.match(source, /aria-valuetext=\{announcement\}/);

  // Verify screen reader live region announcement
  assert.match(source, /role="status"/);
  assert.match(source, /aria-live="polite"/);

  // Verify stage list beneath the progress bar
  assert.match(source, /aria-label="Analysis stages"/);
  assert.match(source, /aria-current=\{active \? 'step' : undefined\}/);
  assert.match(source, /\(completed\)/);
  assert.match(source, /\(current step\)/);
});
