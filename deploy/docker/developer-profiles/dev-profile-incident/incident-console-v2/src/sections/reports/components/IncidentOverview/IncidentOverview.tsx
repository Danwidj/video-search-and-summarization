// SPDX-License-Identifier: Apache-2.0

import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import { currentCameraCount, versionCoverageLabel } from '@/lib/reports/cameras';
import { severityStyle } from '@/lib/ui/severity';
import type { IncidentReportView } from '@/modules/reports/application/types';

const capitalize = (value: string) => value[0].toUpperCase() + value.slice(1);

/** The incident-level fields of the open version, above the chosen camera's report fields. */
export function IncidentOverview({
  view,
}: {
  view: Pick<IncidentReportView, 'overview' | 'coverage' | 'cameras' | 'incidentVideos' | 'revision'>;
}) {
  const { overview, coverage, cameras, incidentVideos, revision } = view;
  return (
    <Card className="mt-5 gap-0 border-border bg-muted/40 py-0 text-sm" data-testid="incident-overview">
      <CardContent className="space-y-2 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-muted-foreground">Incident overview</span>
          <Badge className="px-2 text-[11px]" variant="secondary">
            {versionCoverageLabel(currentCameraCount(cameras), incidentVideos.length, revision.revisionNo)}
          </Badge>
        </div>
        <h2 className="text-base font-semibold leading-snug">{overview.title ?? 'Untitled incident'}</h2>
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {overview.type && <span>{capitalize(overview.type)}</span>}
          {overview.location && <span>{overview.location}</span>}
          {overview.severity_level !== null && (
            <Badge className={`px-2 py-0 text-[11px] font-bold ${severityStyle(overview.severity_level)}`} variant="outline">
              Severity {overview.severity_level}/5
            </Badge>
          )}
        </p>
        {overview.description && <p className="text-sm leading-6 text-foreground/80">{overview.description}</p>}
      </CardContent>
      {coverage.note && (
        <div className="border-t border-border bg-amber-50/80 px-4 py-2 text-xs text-amber-950" data-testid="coverage-note">
          {coverage.note}. Regenerate to build a version from the current videos.
        </div>
      )}
    </Card>
  );
}
