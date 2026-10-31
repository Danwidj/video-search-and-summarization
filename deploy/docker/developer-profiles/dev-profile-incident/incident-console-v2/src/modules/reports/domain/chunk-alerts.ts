// SPDX-License-Identifier: Apache-2.0

// Alert rules per chunk (vss-agent INCIDENT_ALERTS_ENABLED): natural-language
// rules the LLM checked against each caption-pass window. Stored as the agent
// returned them in the run notes (response.chunkAlerts) and read here
// leniently: an entry that is not a usable match is skipped, never repaired.

import type { ChunkWindow } from '@/modules/reports/domain/chunk-timeline';

/** One rule matched by one captioned window, in seconds from the start of the whole video. */
export interface ChunkAlert {
  ruleId: string;
  /** The rule's own text, as the agent's rules file words it. */
  rule: string;
  startSeconds: number;
  endSeconds: number;
  /** The model's one-line reason; empty when it gave none. */
  reason: string;
}

type Row = Record<string, unknown>;

const asRow = (value: unknown): Row | null => (value && typeof value === 'object' && !Array.isArray(value) ? (value as Row) : null);
const seconds = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null);
const text = (value: unknown): string => (typeof value === 'string' ? value.trim() : '');

/** The usable matches of stored chunk alerts, ordered by start; empty when there are none. */
export function chunkAlertsFrom(raw: unknown): ChunkAlert[] {
  if (!Array.isArray(raw)) return [];
  const alerts: ChunkAlert[] = [];
  for (const entry of raw) {
    const row = asRow(entry);
    if (!row) continue;
    const start = seconds(row.start);
    const end = seconds(row.end);
    const ruleId = text(row.rule_id);
    const rule = text(row.rule);
    if (start === null || end === null || end <= start || !ruleId || !rule) continue;
    alerts.push({ ruleId, rule, startSeconds: start, endSeconds: end, reason: text(row.reason) });
  }
  return alerts.sort((a, b) => a.startSeconds - b.startSeconds || a.endSeconds - b.endSeconds);
}

// The agent copies a window's own bounds into each match, so equal bounds identify the window.
const sameBounds = (a: number, b: number) => Math.abs(a - b) < 1e-3;

/**
 * The alerts of each window, by position in `windows`: matched on the window's
 * bounds (the agent's window_index counts windows before the console drops
 * unusable ones, so it is not used). An alert whose window is not in the list
 * belongs to none.
 */
export function alertsByWindow(windows: ChunkWindow[], alerts: ChunkAlert[]): ChunkAlert[][] {
  return windows.map((window) =>
    alerts.filter((alert) => sameBounds(alert.startSeconds, window.startSeconds) && sameBounds(alert.endSeconds, window.endSeconds)),
  );
}
