// SPDX-License-Identifier: Apache-2.0

// Calendar periods for dashboard charts: a model reply may name one month, one day or a from and to pair, and it counts
// only when it is a real date, not reversed, at most 366 days long and not starting after today in the viewer's time zone.
// A month or range that ends after today is charted up to today and titled "(to date)".

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { parseChartSpec, chartAllowlist, CHART_PERIODS } = await import('../src/modules/dashboard/domain/chart-spec.ts');
const { CALENDAR_MAX_DAYS, calendarDays, calendarWords, startOfDay, todayIn, addDays } = await import(
  '../src/modules/dashboard/domain/chart-period.ts'
);

const TODAY = '2026-10-31';
const spec = (period) => ({
  metric: 'incidents',
  dimension: 'report_day',
  period,
  incidentType: null,
  severity: null,
});

describe('calendar periods that count', () => {
  const valid = {
    'a past month': { month: '2026-10' },
    'a month in a past year': { month: '2025-02' },
    'a day': { day: '2026-10-28' },
    today: { day: TODAY },
    'a range': { from: '2026-10-01', to: '2026-10-15' },
    'a range of one day': { from: '2026-10-15', to: '2026-10-15' },
    'a range of exactly the maximum span': { from: '2025-10-31', to: '2026-10-31' },
    'a range that runs past today': { from: '2026-10-25', to: '2026-11-02' },
    'a range that starts today and runs past it': { from: '2026-10-31', to: '2026-12-31' },
    'the presets, as before': 'last_30_days',
  };
  for (const [name, period] of Object.entries(valid)) {
    test(`accepts ${name}`, () => {
      assert.notEqual(parseChartSpec(spec(period), TODAY), null, name);
    });
  }

  test('a month still running is accepted and counts up to today', () => {
    assert.notEqual(parseChartSpec(spec({ month: '2026-10' }), '2026-10-06'), null);
    assert.deepEqual(calendarDays({ month: '2026-10' }, '2026-10-06'), { first: '2026-10-01', last: '2026-10-06' });
  });

  test('a range that runs past today is clamped to end today', () => {
    assert.deepEqual(calendarDays({ from: '2026-10-01', to: '2026-12-31' }, '2026-11-07'), { first: '2026-10-01', last: '2026-11-07' });
    assert.deepEqual(calendarDays({ from: '2026-10-25', to: '2026-11-02' }, TODAY), { first: '2026-10-25', last: '2026-10-31' });
  });

  test('the maximum span is measured on the days charted, so a range clamped to today may be longer as written', () => {
    assert.notEqual(calendarDays({ from: '2025-11-07', to: '2026-12-31' }, '2026-11-07'), null);
    assert.equal(calendarDays({ from: '2025-11-06', to: '2026-12-31' }, '2026-11-07'), null);
  });

  test('the spec keeps a range that runs past today as written, for generateChart to clamp', () => {
    assert.deepEqual(parseChartSpec(spec({ from: '2026-10-01', to: '2026-12-31' }), '2026-11-07').period, {
      from: '2026-10-01',
      to: '2026-12-31',
    });
  });

  test('the preset shape is unchanged, so old answers still parse', () => {
    for (const preset of Object.keys(CHART_PERIODS)) {
      assert.equal(parseChartSpec(spec(preset), TODAY).period, preset);
    }
  });
});

describe('calendar periods that are refused', () => {
  const refused = {
    'a month after today': { month: '2026-11' },
    'a month a year ahead': { month: '2027-01' },
    'a day after today': { day: '2026-11-01' },
    'a range that starts after today': { from: '2026-11-01', to: '2026-11-03' },
    'a range entirely in the future, like next month': { from: '2026-11-01', to: '2026-11-30' },
    'a reversed range': { from: '2026-10-15', to: '2026-10-01' },
    'a range over the maximum span': { from: '2025-10-30', to: '2026-10-31' },
    'a day that does not exist': { day: '2026-02-30' },
    'a month that does not exist': { month: '2026-13' },
    'a month without a leading zero': { month: '2026-1' },
    'a day without a leading zero': { day: '2026-10-3' },
    'a day with a time': { day: '2026-10-28T10:00' },
    'a date typed as a string': '2026-10-28',
    'a month and a day in one object': { month: '2026-10', day: '2026-10-28' },
    'a range missing its end': { from: '2026-10-01' },
    'a range with an extra key': { from: '2026-10-01', to: '2026-10-15', label: 'October' },
    'an empty period': {},
    'a calendar period with a non-string date': { day: 20261028 },
    'a period naming a word': 'october',
    'a day in year 0000': { day: '0000-01-01' },
    'a month in year 0000': { month: '0000-01' },
    'a range from year 0000': { from: '0000-12-31', to: '0001-01-01' },
  };
  for (const [name, period] of Object.entries(refused)) {
    test(`refuses ${name}`, () => {
      assert.equal(parseChartSpec(spec(period), TODAY), null, name);
    });
  }

  test('refusal does not depend on the period being a preset', () => {
    assert.equal(parseChartSpec(spec({ month: '2026-11' }), '2026-10-31'), null);
    assert.notEqual(parseChartSpec(spec({ month: '2026-11' }), '2026-11-30'), null);
  });
});

describe('the calendar day is the viewer time zone day', () => {
  test('todayIn reads the day in the zone, not in UTC', () => {
    const late = new Date('2026-10-31T20:00:00Z');
    assert.equal(todayIn('UTC', late), '2026-10-31');
    assert.equal(todayIn('Asia/Singapore', late), '2026-11-01');
    assert.equal(todayIn('America/New_York', late), '2026-10-31');
  });

  test('startOfDay is local midnight in the zone, across a daylight saving change', () => {
    assert.deepEqual(startOfDay('2026-10-28', 'UTC'), new Date('2026-10-28T00:00:00Z'));
    assert.deepEqual(startOfDay('2026-10-28', 'Asia/Singapore'), new Date('2026-10-27T16:00:00Z'));
    // New York moves to daylight time on 8 March 2026: midnight is 05:00 UTC before, 04:00 UTC after.
    assert.deepEqual(startOfDay('2026-03-08', 'America/New_York'), new Date('2026-03-08T05:00:00Z'));
    assert.deepEqual(startOfDay('2026-03-09', 'America/New_York'), new Date('2026-03-09T04:00:00Z'));
  });

  test('startOfDay is the first instant of the day where daylight saving skips midnight', () => {
    // Santiago and Havana jump from 00:00 to 01:00, so the day starts at 01:00 local, not 23:00 the day before.
    const santiago = startOfDay('2026-09-06', 'America/Santiago');
    assert.deepEqual(santiago, new Date('2026-09-06T04:00:00Z'));
    assert.equal(todayIn('America/Santiago', santiago), '2026-09-06');
    assert.equal(todayIn('America/Santiago', new Date(santiago.getTime() - 1)), '2026-09-05');
    const havana = startOfDay('2026-03-08', 'America/Havana');
    assert.deepEqual(havana, new Date('2026-03-08T05:00:00Z'));
    assert.equal(todayIn('America/Havana', havana), '2026-03-08');
    assert.equal(todayIn('America/Havana', new Date(havana.getTime() - 1)), '2026-03-07');
  });

  test('addDays moves across a month and a year', () => {
    assert.equal(addDays('2026-10-31', 1), '2026-11-01');
    assert.equal(addDays('2026-12-31', 1), '2027-01-01');
    assert.equal(addDays('2026-03-01', -1), '2026-02-28');
  });
});

describe('the words for a period', () => {
  test('a whole month is named by its month and year', () => {
    assert.equal(calendarWords({ month: '2026-10' }, TODAY), 'October 2026');
  });

  test('a day, and a range in the same month, year or across them', () => {
    assert.equal(calendarWords({ day: '2026-11-06' }, '2026-11-06'), '6 November 2026');
    assert.equal(calendarWords({ from: '2026-10-01', to: '2026-10-15' }, TODAY), '1 to 15 October 2026');
    assert.equal(calendarWords({ from: '2026-10-25', to: '2026-11-03' }, '2026-11-03'), '25 October to 3 November 2026');
    assert.equal(calendarWords({ from: '2025-12-29', to: '2026-01-02' }, TODAY), '29 December 2025 to 2 January 2026');
  });

  test('a month still running is titled by the days charted, and says it is to date', () => {
    assert.equal(calendarWords({ month: '2026-10' }, '2026-10-06'), '1 to 6 October 2026 (to date)');
    assert.equal(calendarWords({ month: '2026-11' }, '2026-11-07'), '1 to 7 November 2026 (to date)');
    assert.equal(calendarWords({ month: '2026-10' }, '2026-10-31'), 'October 2026');
  });

  test('a range that reaches past today is titled to date, and names the days charted', () => {
    assert.equal(calendarWords({ from: '2026-10-01', to: '2026-12-31' }, '2026-11-07'), '1 October to 7 November 2026 (to date)');
    assert.equal(calendarWords({ from: '2025-12-29', to: '2026-12-31' }, '2026-01-02'), '29 December 2025 to 2 January 2026 (to date)');
  });

  test('the maximum span is the one the allowlist publishes', () => {
    assert.equal(chartAllowlist().calendarPeriods.maxRangeDays, CALENDAR_MAX_DAYS);
    assert.equal(CALENDAR_MAX_DAYS, 366);
  });
});
