// SPDX-License-Identifier: Apache-2.0

// Calendar periods for dashboard charts: one month, one day, or the days from one date to another (inclusive).
// Dates are the viewer's own calendar days (YYYY-MM-DD, no times). The presets stay in chart-spec.ts.
// A model reply that names a calendar period is checked here, against today's date in the viewer's time zone.

export const CALENDAR_MAX_DAYS = 366;

export type CalendarPeriod = { month: string } | { day: string } | { from: string; to: string };

/** The days a period covers, first to last inclusive, as YYYY-MM-DD. */
export interface DayRange {
  first: string;
  last: string;
}

const DAY_MS = 86_400_000;
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/;
const ISO_MONTH = /^\d{4}-\d{2}$/;

/** A YYYY-MM-DD that is a real calendar day (no 30 February), and nothing else. */
export function isRealDay(text: string): boolean {
  if (!ISO_DAY.test(text)) return false;
  return new Date(`${text}T00:00:00Z`).toISOString().slice(0, 10) === text;
}

/** A YYYY-MM whose month is 01 to 12. */
export function isRealMonth(text: string): boolean {
  if (!ISO_MONTH.test(text)) return false;
  const month = Number(text.slice(5));
  return month >= 1 && month <= 12;
}

/** The day `count` days after a YYYY-MM-DD day (before it when negative). */
export function addDays(day: string, count: number): string {
  return new Date(Date.parse(`${day}T00:00:00Z`) + count * DAY_MS).toISOString().slice(0, 10);
}

/** The days in a range, inclusive. */
function spanDays(range: DayRange): number {
  return (Date.parse(`${range.last}T00:00:00Z`) - Date.parse(`${range.first}T00:00:00Z`)) / DAY_MS + 1;
}

/**
 * The days a calendar period covers, or null when it is not a period the viewer can chart today: a malformed or
 * unreal date, a reversed range, a range over CALENDAR_MAX_DAYS, a day or range that reaches past today, or a month
 * that starts after today. A month still running is clipped to today, so "November" on 6 November covers 1 to 6 November.
 */
export function calendarDays(period: CalendarPeriod, today: string): DayRange | null {
  if ('month' in period) {
    if (!isRealMonth(period.month)) return null;
    const first = `${period.month}-01`;
    if (first > today) return null;
    const monthEnd = monthLastDay(period.month);
    return { first, last: monthEnd > today ? today : monthEnd };
  }
  if ('day' in period) {
    if (!isRealDay(period.day) || period.day > today) return null;
    return { first: period.day, last: period.day };
  }
  if (!isRealDay(period.from) || !isRealDay(period.to)) return null;
  const range = { first: period.from, last: period.to };
  if (range.first > range.last || range.last > today) return null;
  return spanDays(range) > CALENDAR_MAX_DAYS ? null : range;
}

/** The last day of a YYYY-MM month. */
function monthLastDay(month: string): string {
  const [year, monthNumber] = month.split('-').map(Number) as [number, number];
  // Day 0 of the next month is the last day of this one.
  return new Date(Date.UTC(year, monthNumber, 0)).toISOString().slice(0, 10);
}

/** "October 2026", "6 November 2026", "1 to 15 October 2026" or "1 October to 15 November 2026", in English. */
export function rangeWords({ first, last }: DayRange): string {
  const [y1, m1, d1] = first.split('-').map(Number) as [number, number, number];
  const [y2, m2, d2] = last.split('-').map(Number) as [number, number, number];
  const month1 = MONTHS[m1 - 1];
  const month2 = MONTHS[m2 - 1];
  if (first === last) return `${d1} ${month1} ${y1}`;
  if (y1 === y2 && m1 === m2) return `${d1} to ${d2} ${month1} ${y1}`;
  if (y1 === y2) return `${d1} ${month1} to ${d2} ${month2} ${y1}`;
  return `${d1} ${month1} ${y1} to ${d2} ${month2} ${y2}`;
}

/** The words for a calendar period on `today`: a whole month is named by its month, anything else by its days. */
export function calendarWords(period: CalendarPeriod, today: string): string {
  const days = calendarDays(period, today);
  if (!days) throw new Error('calendarWords needs a period that calendarDays accepts');
  if ('month' in period && days.last === monthLastDay(period.month)) {
    const [year, month] = period.month.split('-').map(Number) as [number, number];
    return `${MONTHS[month - 1]} ${year}`;
  }
  return rangeWords(days);
}

/** The calendar day in `timeZone` at `now`, as YYYY-MM-DD. */
export function todayIn(timeZone: string, now: Date): string {
  const parts = new Intl.DateTimeFormat('en-US', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  const value = (type: Intl.DateTimeFormatPartTypes) => parts.find((part) => part.type === type)?.value ?? '';
  return `${value('year')}-${value('month')}-${value('day')}`;
}

/** The wall clock in `timeZone` at `instant`, read as if it were UTC. */
function wallClock(instant: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: 'numeric',
    minute: 'numeric',
    second: 'numeric',
  }).formatToParts(new Date(instant));
  const value = (type: Intl.DateTimeFormatPartTypes) => Number(parts.find((part) => part.type === type)?.value);
  return Date.UTC(value('year'), value('month') - 1, value('day'), value('hour'), value('minute'), value('second'));
}

/** Local midnight at the start of a YYYY-MM-DD day in `timeZone`. Two passes settle an offset that changes on that day. */
export function startOfDay(day: string, timeZone: string): Date {
  const [year, month, date] = day.split('-').map(Number) as [number, number, number];
  const wall = Date.UTC(year, month - 1, date);
  const first = wall - (wallClock(wall, timeZone) - wall);
  return new Date(wall - (wallClock(first, timeZone) - first));
}
