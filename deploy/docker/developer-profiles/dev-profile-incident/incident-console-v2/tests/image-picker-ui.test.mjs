// SPDX-License-Identifier: Apache-2.0

// Set image in Edit mode: the card control, the dialog around it and what Done puts on the draft.

import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const sections = new URL('../src/sections/', import.meta.url);

test('only the image of an Edit card opens Set image, with a hover hint and no extra button', async () => {
  const pane = await readFile(new URL('reports/components/ReportEditPane/ReportEditPane.tsx', sections), 'utf8');
  assert.doesNotMatch(pane, /^\s*Set image\s*$/m, 'no Set image button beside Edit track');
  assert.match(pane, /onSetImage=\{onSetImage\}\s+previewVideoSrc/, 'EditCard hands it to the image only');
  assert.match(pane, /onClick=\{\(\) => \(onSetImage \? onSetImage\(\)/, 'the image button opens it');
  assert.match(pane, /data-testid=\{onSetImage \? 'set-image'/);
  assert.match(pane, /group-hover:opacity-100[\s\S]*?group-focus-visible:opacity-100/, 'hover and keyboard focus show the hint');
  assert.equal(pane.match(/setImagePicker\(\{/g)?.length, 1, 'one place opens the picker');
  assert.match(pane, /disabled=\{!onSetImage && seconds === null\}/, 'an item with no image second can still be clicked');
  assert.match(pane, /seed=\{pickSeed\(imagePicker\.row, imagePicker\.saved\)\}/);
  assert.match(pane, /setImagePick\(draft, itemKind\(target\), target\.key, pick\)/);
  assert.match(pane, /pick \? pick\.box : item\.imageBox/, 'the card shows the frame and box that were picked');
});

test('the picker draws on a frame of the report video and shows the crop the server will store', async () => {
  const dialog = await readFile(new URL('evidence/components/EvidenceImagePicker/EvidenceImagePicker.tsx', sections), 'utf8');
  assert.match(dialog, /<BoxCanvas box=\{box\} drawable onDraw=\{setBox\}/, 'the mouse draws the crop');
  assert.match(dialog, /evidence-crop/, "the preview is the crop route's answer");
  assert.match(dialog, /bg-muted\/40 px-6 py-5 pr-24/, 'the title band matches Edit track');
  assert.match(dialog, /disabled=\{!ready\}/, 'Use this image waits for a drawn crop that was cut');
  assert.match(dialog, /onDone\(\{ seconds, box \}\)/, 'Done hands back the second and the box only');
  assert.match(dialog, /setBox\(null\)/, 'moving to another frame clears a crop drawn on the old one');
  assert.doesNotMatch(dialog, /<input|type="file"/, 'no file upload from disk');
});
