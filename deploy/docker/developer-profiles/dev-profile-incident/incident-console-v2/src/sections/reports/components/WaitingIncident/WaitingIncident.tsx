// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';

import { incidentScope } from '@/lib/reports/incident-notices';
import { IncidentNotice } from '@/sections/reports/components/IncidentNotice';
import { EmptyIncident } from '@/sections/reports/components/EmptyIncident';
import { RegenerateReport } from '@/sections/reports/components/RegenerateReport';
import { SuggestionBanner } from '@/sections/suggestions/components/SuggestionBanner';

export interface WaitingVideo {
  name: string;
  playbackUrl: string | null;
}

/**
 * The page of an incident that has videos but no version yet: it is waiting for a match decision or a build. It shows
 * the videos, the pending suggestions to decide (accepting one builds the report) and a way to build the report now.
 * With no videos at all there is nothing to wait for, so it is the empty incident's page instead.
 */
export function WaitingIncident({ incidentId, videos, onBuilt }: { incidentId: string; videos: WaitingVideo[]; onBuilt: () => void }) {
  if (videos.length === 0) return <EmptyIncident incidentId={incidentId} />;
  return (
    <div className="pb-16" data-testid="waiting-incident">
      <div className="overflow-hidden border-y border-border bg-card shadow-panel">
        <div className="border-b border-border px-5 py-4 sm:px-8">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-amber-800">No report yet</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Incident {incidentId} is waiting</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            Its video{videos.length === 1 ? ' is' : 's are'} analysed, but the report is built once any suggested match is decided. Decide
            below, or build the report now from the stored analyses.
          </p>
        </div>
        <IncidentNotice flush fromIncidentId={Number(incidentId)} scope={incidentScope(Number(incidentId))} />
        <SuggestionBanner incidentId={Number(incidentId)} onMerged={onBuilt} />
        <RegenerateReport
          caption="Build the report now, without waiting for a match decision"
          incidentId={incidentId}
          label="Build report now"
          onDone={onBuilt}
          videoCount={videos.length}
        />
        <ul className="grid gap-4 p-5 sm:p-8 md:grid-cols-2">
          {videos.map((video) => (
            <li className="min-w-0 space-y-2" data-testid="waiting-video" key={video.name}>
              {video.playbackUrl ? (
                // biome-ignore lint/a11y/useMediaCaption: surveillance clip without a caption track
                <video className="aspect-video w-full rounded-lg bg-black" controls preload="metadata" src={video.playbackUrl} />
              ) : (
                <div className="grid aspect-video w-full place-items-center rounded-lg bg-muted text-xs text-muted-foreground">
                  Video unavailable
                </div>
              )}
              <p className="truncate text-sm font-medium">{video.name}</p>
            </li>
          ))}
        </ul>
        <div className="border-t border-border px-5 py-3 text-xs sm:px-8">
          <Link className="font-semibold text-moss hover:underline" href="/library">
            Back to the library
          </Link>
        </div>
      </div>
    </div>
  );
}
