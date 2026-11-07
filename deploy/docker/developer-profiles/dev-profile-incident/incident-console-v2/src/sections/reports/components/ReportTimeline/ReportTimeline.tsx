// SPDX-License-Identifier: Apache-2.0
'use client';

import { EvidenceFrame, KIND_COLOUR } from '@/sections/evidence/components/EvidenceFrame';
import { axisPercent, axisTicks, buildTimelineLanes, timelineDuration, type LaneMarker } from '@/lib/reports/timeline-lanes';
import { formatClock } from '@/modules/reports/domain/normalize';
import type { ReportView } from '@/modules/reports/domain/report-view';

const MARKER_SHAPE: Record<LaneMarker['kind'], string> = { entity: 'rounded-full', instrument: 'rotate-45', asset: '' };
const LEGEND_LABEL: Record<LaneMarker['kind'], string> = { entity: 'Entities', instrument: 'Instruments', asset: 'Assets' };

export function ReportTimeline({
  structured,
  videoSeconds,
  currentTime,
  onSeek,
  bare = false,
}: {
  structured: ReportView['structured'];
  videoSeconds: number | null;
  currentTime: number;
  /** The Edit page's timeline: a plain heading and no legend, as its mockup shows. */
  bare?: boolean;
  onSeek: (seconds: number) => void;
}) {
  const lanes = buildTimelineLanes(structured);
  const duration = timelineDuration(lanes, videoSeconds);
  const ticks = axisTicks(duration);
  const playhead = axisPercent(currentTime, duration);

  return (
    <section aria-label="Timeline" className="flex h-full min-h-0 flex-col bg-card" data-testid="report-timeline">
      {bare ? (
        <div className="px-3 pt-2 font-mono text-[10px] font-bold uppercase tracking-[0.1em] text-muted-foreground">Timeline</div>
      ) : (
        <div className="border-b border-l-4 border-border/70 border-l-primary bg-primary/5 px-3 py-2.5">
          <h3 className="text-sm font-semibold text-foreground">Timeline · one lane per entity and what they hold</h3>
          <p className="mt-1 flex gap-3 text-[10.5px] font-bold uppercase tracking-wide text-muted-foreground">
            {(['entity', 'instrument', 'asset'] as const).map((kind) => (
              <span className="flex items-center gap-1" key={kind}>
                <i className={`inline-block size-2 ${MARKER_SHAPE[kind]} ${KIND_COLOUR[kind]}`} />
                {LEGEND_LABEL[kind]}
              </span>
            ))}
          </p>
        </div>
      )}
      {lanes.length === 0 ? (
        <p className="px-3 py-4 text-sm text-muted-foreground" data-testid="timeline-empty">
          This version has no evidence items to place on a timeline.
        </p>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2.5">
          <div className="sticky top-0 z-10 mb-2 grid grid-cols-[110px_minmax(0,1fr)] items-center gap-2 bg-card pt-1 font-mono text-[10px] text-muted-foreground">
            <span />
            <div className="flex justify-between">
              {ticks.map((tick) => (
                <span key={tick}>{formatClock(tick)}</span>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-2">
            {lanes.map((lane) => (
              <div className="grid grid-cols-[110px_minmax(0,1fr)] items-center gap-2 text-xs" data-lane={lane.id} key={lane.id}>
                <div className="flex items-center gap-1.5 overflow-hidden pr-1 font-medium text-foreground">
                  {lane.kind === 'entity' && (lane.imageUrl || lane.frame) && (
                    <EvidenceFrame
                      aspect={1}
                      box={lane.frame?.box}
                      className="h-4 w-4 shrink-0 !rounded-md"
                      frameSrc={lane.frame?.src}
                      label={lane.title}
                      src={lane.imageUrl}
                    />
                  )}
                  <span className="truncate text-[11px]" title={lane.title}>
                    {lane.title}
                  </span>
                </div>
                <button
                  aria-label={`Move the video along ${lane.title}`}
                  className="relative h-2.5 w-full cursor-pointer rounded-full bg-moss/20"
                  onClick={(event) => {
                    const box = event.currentTarget.getBoundingClientRect();
                    const percent = Math.max(0, Math.min(1, (event.clientX - box.left) / box.width));
                    onSeek(Math.round(percent * duration));
                  }}
                  type="button"
                >
                  {lane.span && (
                    <span
                      className="absolute top-0 bottom-0 rounded-full bg-moss"
                      data-testid="lane-span"
                      style={{
                        left: `${axisPercent(lane.span.start, duration)}%`,
                        width: `${Math.max(1, axisPercent(lane.span.end, duration) - axisPercent(lane.span.start, duration))}%`,
                      }}
                    />
                  )}
                  {lane.markers.map((marker) => {
                    const seconds = marker.seconds;
                    if (seconds === null) return null;
                    return (
                      <span
                        aria-label={`${marker.label} at ${formatClock(seconds)}`}
                        className={`absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 border-2 border-background ${MARKER_SHAPE[marker.kind]} ${KIND_COLOUR[marker.kind]}`}
                        data-marker={marker.id}
                        key={`${marker.kind}-${marker.id}`}
                        role="img"
                        style={{ left: `${axisPercent(seconds, duration)}%` }}
                        title={`${marker.label} · ${formatClock(seconds)}`}
                      />
                    );
                  })}
                  <div
                    aria-hidden
                    className="pointer-events-none absolute top-[-4px] bottom-[-4px] w-0.5 -translate-x-1/2 bg-foreground"
                    data-testid="playhead"
                    style={{ left: `${playhead}%` }}
                  />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
