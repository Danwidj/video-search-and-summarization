// SPDX-License-Identifier: Apache-2.0

// The three example chips under "Ask for a chart": exactly these requests, each with a kind that the dimension it
// targets draws well (a donut for a whole, the stacked view for severity within each type).

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { CHART_EXAMPLES } = await import('../src/sections/dashboard/components/ChartRequest/chart-examples.ts');
const { kindFitsDimension, drawnKind } = await import('../src/modules/dashboard/domain/chart-kinds.ts');

test('the panel offers exactly the three example chips, the October breakdown first', () => {
  assert.deepEqual(
    CHART_EXAMPLES.map((example) => example.request),
    [
      'Break down each incident type by severity throughout October',
      'Share of each incident type throughout October',
      'Severity mix of assault incidents in the last 90 days',
    ],
  );
});

test('each chip carries a chart kind that fits the dimension it asks for', () => {
  const [october, incidentTypes, severity] = CHART_EXAMPLES;
  // The view ignores the kind it is sent with: the drawn kind is the view's own (a stacked bar by severity).
  assert.equal(drawnKind(october.kind, 'incident_type_severity'), 'stacked_by_severity');
  assert.equal(kindFitsDimension(october.kind, 'incident_type_severity'), true);
  assert.equal(incidentTypes.kind, 'donut');
  assert.equal(kindFitsDimension(incidentTypes.kind, 'incident_type'), true);
  assert.equal(severity.kind, 'donut');
  assert.equal(kindFitsDimension(severity.kind, 'severity'), true);
});

test('a click sets the picker to the chip kind, except for the view, which leaves the picker alone', () => {
  const [october, incidentTypes, severity] = CHART_EXAMPLES;
  assert.equal(october.setsPicker, false);
  assert.equal(incidentTypes.setsPicker, true);
  assert.equal(severity.setsPicker, true);
});
