// SPDX-License-Identifier: Apache-2.0

import assert from 'node:assert/strict';
import { register } from 'node:module';
import test from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const {
  DEFAULT_REPORT_BAND_HEIGHT,
  DEFAULT_REPORT_BAND_WIDTHS,
  nudgeReportBand,
  nudgeReportBandHeight,
  resizeReportBand,
  resizeReportBandHeight,
} = await import('../src/lib/reports/report-band-layout.ts');

function assertWidths(actual, expected) {
  for (const key of ['video', 'timeline', 'versions']) assert.ok(Math.abs(actual[key] - expected[key]) < 1e-12, `${key} width`);
  assert.ok(Math.abs(actual.video + actual.timeline + actual.versions - 1) < 1e-12, 'the widths total one');
}

test('either report-band boundary resizes its neighbours and preserves the total width', () => {
  assertWidths(resizeReportBand(DEFAULT_REPORT_BAND_WIDTHS, 'video-timeline', 0.4), {
    video: 0.4,
    timeline: 0.4,
    versions: 0.2,
  });
  assertWidths(resizeReportBand(DEFAULT_REPORT_BAND_WIDTHS, 'timeline-versions', 0.7), {
    video: 0.3,
    timeline: 0.4,
    versions: 0.3,
  });
});

test('report-band sections cannot be dragged or nudged below their minimum width', () => {
  assertWidths(resizeReportBand(DEFAULT_REPORT_BAND_WIDTHS, 'video-timeline', 0), {
    video: 0.15,
    timeline: 0.65,
    versions: 0.2,
  });
  assertWidths(resizeReportBand(DEFAULT_REPORT_BAND_WIDTHS, 'timeline-versions', 1), {
    video: 0.3,
    timeline: 0.55,
    versions: 0.15,
  });
  assert.equal(nudgeReportBand({ video: 0.15, timeline: 0.65, versions: 0.2 }, 'video-timeline', -1).video, 0.15);
});

test('the report band height can be dragged or nudged within its limits', () => {
  assert.equal(resizeReportBandHeight(360), 360);
  assert.equal(resizeReportBandHeight(10), 190);
  assert.equal(resizeReportBandHeight(900), 600);
  assert.equal(nudgeReportBandHeight(DEFAULT_REPORT_BAND_HEIGHT, -1), 250);
  assert.equal(nudgeReportBandHeight(600, 1), 600);
});
