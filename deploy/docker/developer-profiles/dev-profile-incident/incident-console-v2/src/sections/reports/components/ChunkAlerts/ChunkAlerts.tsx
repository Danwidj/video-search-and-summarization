// SPDX-License-Identifier: Apache-2.0
'use client';

import { FlagIcon } from 'lucide-react';

import type { ChunkAlert } from '@/modules/reports/domain/chunk-alerts';
import { formatClock } from '@/modules/reports/domain/normalize';

/**
 * The alert rules the run's caption windows matched, at the top of the report:
 * one row per match with the rule, the window's time and the model's reason.
 * A click moves the playhead to the window's start. Rendered only when there is a match.
 */
export function ChunkAlerts({ alerts, onSeek }: { alerts: ChunkAlert[]; onSeek: (seconds: number) => void }) {
  return (
    <section
      aria-label="Alerts"
      className="mt-5 rounded-lg border border-amber-300 bg-amber-50/70 text-sm text-amber-950"
      data-testid="chunk-alerts"
    >
      <div className="flex items-baseline gap-3 px-4 pt-3 pb-1">
        <h2 className="flex items-center gap-1.5 font-mono text-[10.5px] font-bold uppercase tracking-[0.14em]">
          <FlagIcon aria-hidden="true" className="size-3.5" />
          Alerts
        </h2>
        <span className="text-xs text-amber-900/80">
          Alert rules matched by the caption timeline: model output, not evidence. Select one to jump there.
        </span>
      </div>
      <ul className="m-0 list-none px-2 pb-2">
        {alerts.map((alert) => (
          <li key={`${alert.ruleId}-${alert.startSeconds}-${alert.endSeconds}`}>
            <button
              className="grid w-full grid-cols-[6.5rem_1fr] gap-4 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-amber-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="chunk-alert"
              onClick={() => onSeek(alert.startSeconds)}
              type="button"
            >
              <span className="pt-px font-mono text-xs tabular-nums">
                {formatClock(alert.startSeconds)}–{formatClock(alert.endSeconds)}
              </span>
              <span className="leading-5">
                <b className="font-semibold">{alert.rule}</b>
                {alert.reason && <span className="block text-amber-900/80">{alert.reason}</span>}
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
