// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { test } from 'node:test';

const components = join(process.cwd(), 'src', 'sections', 'library', 'components');
const read = (file) => readFileSync(join(components, file), 'utf8');

test('a library card opens the incident, shows its video count and names the first video with the rest counted', () => {
  const card = read('IncidentCard/IncidentCard.tsx');
  assert.match(card, /\/reports\/\$\{encodeURIComponent\(item\.incidentId\)\}/);
  assert.match(card, /videoCount=\{item\.videoCount\}/);
  assert.match(card, /\$\{firstVideo\} \+\$\{item\.videoCount - 1\} more/);
  assert.match(read('ReportThumbnail/ReportThumbnail.tsx'), /data-testid="video-count"/);
});

test('the delete dialog says every video, analysis, version and evidence image goes', () => {
  const dialog = read('IncidentCard/DeleteIncidentDialog.tsx');
  assert.match(dialog, /all \$\{item\.videoCount\} of its videos/);
  assert.match(dialog, /every analysis of them/);
  assert.match(dialog, /evidence images/);
});

test('an evidence hit names its camera beside the incident', () => {
  assert.match(read('HitCard/HitCard.tsx'), /data-testid="hit-camera"/);
});
