// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { EditIcon, EyeIcon, HistoryIcon, MoreHorizontalIcon } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { EvidenceFrame, KIND_COLOUR, KIND_LABEL } from '@/sections/evidence/components/EvidenceFrame';
import { IncidentThumbnail, SeverityChip } from '@/sections/library/components/Shared';
import { type HitRelationship, type SearchedVersion, matchPercent, reportHref } from '@/lib/library/search';
import type { EvidenceSearchHit } from '@/modules/search/domain/search';
import { formatClock } from '@/modules/reports/domain/normalize';

export function RelationshipLine({ relationship }: { relationship: HitRelationship }) {
  const parts: string[] = [];
  if (relationship.heldBy)
    parts.push(`held by ${relationship.heldBy.itemId}${relationship.heldBy.name ? ` (${relationship.heldBy.name})` : ''}`);
  if (relationship.holds.length) parts.push(`holds ${relationship.holds.map((held) => held.itemId).join(', ')}`);
  return parts.length ? (
    <p className="truncate text-xs text-ink-caption" data-testid="hit-relationship">
      {parts.join(' · ')}
    </p>
  ) : null;
}

export function HitCard({
  hit,
  version,
  relationship,
  onView,
  showMatch = true,
  onShowInIncidents,
}: {
  hit: EvidenceSearchHit;
  version?: SearchedVersion;
  relationship: HitRelationship;
  onView: () => void;
  /** False for a listing with no query, which has no similarity to show. */
  showMatch?: boolean;
  onShowInIncidents?: (incident: EvidenceSearchHit['incident']) => void;
}) {
  const router = useRouter();
  const { item, incident } = hit;
  const href = reportHref(hit, version);
  const clock = formatClock(item.timestampSeconds);
  const label = `${item.itemId} · ${item.name || item.label}`;

  return (
    <Card
      data-testid="evidence-hit"
      role="link"
      tabIndex={0}
      aria-label={`Open report at ${clock}: ${label}`}
      className="group relative flex max-h-[40vh] cursor-pointer flex-col overflow-hidden rounded-xl border border-ink/10 bg-white p-0 shadow-xs transition hover:border-ink/25 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss"
      onClick={(event) => {
        if (!event.currentTarget.contains(event.target as Node)) return;
        if ((event.target as HTMLElement).closest('[data-no-card-nav]')) return;
        router.push(href);
      }}
      onKeyDown={(event) => {
        if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          router.push(href);
        }
      }}
    >
      <div className="relative h-24 shrink-0 overflow-hidden bg-[#dfe3dc]">
        <button
          aria-label={`View ${item.name || item.itemId} in its frame`}
          className="relative block h-full w-full text-left"
          data-no-card-nav
          onClick={onView}
          type="button"
        >
          <EvidenceFrame
            aspect={16 / 9}
            box={item.boundingBox}
            className="h-full w-full rounded-none"
            drawBox
            frameSrc={`/api/reports/${encodeURIComponent(incident.incidentId)}/frame?t=${item.timestampSeconds}`}
            kind={item.itemType}
            label={item.name || item.itemId}
            src={item.cropImageUrl}
          />
        </button>

        <Badge
          variant="outline"
          className="absolute left-2.5 top-2.5 h-auto rounded-full border border-ink/10 bg-white px-2 py-0.5 text-[11px] font-bold text-ink shadow-xs"
          data-testid="hit-match"
        >
          {showMatch ? `${matchPercent(hit)}% match` : 'In incident'}
        </Badge>

        <span className="absolute bottom-2 left-2.5 rounded bg-ink/80 px-1.5 py-0.5 font-mono text-[11px] text-white">{clock}</span>

        <div className="absolute right-2 top-2 z-10" data-no-card-nav>
          <TooltipProvider>
            <DropdownMenu>
              <Tooltip>
                <TooltipTrigger asChild>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      size="icon"
                      className="size-8 rounded-md border-ink/10 bg-white text-ink shadow-xs hover:bg-white/90 data-[state=open]:bg-ink data-[state=open]:text-white"
                      aria-label={`Actions for ${label}`}
                    >
                      <MoreHorizontalIcon className="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                </TooltipTrigger>
                <TooltipContent>More actions</TooltipContent>
              </Tooltip>
              <DropdownMenuContent
                align="end"
                className="w-56 bg-white"
                onClick={(event) => event.stopPropagation()}
                onPointerDown={(event) => event.stopPropagation()}
              >
                <DropdownMenuItem asChild>
                  <Link className="flex cursor-pointer items-center gap-2" href={href}>
                    <EditIcon className="size-4" />
                    <span>Open report at {clock}</span>
                  </Link>
                </DropdownMenuItem>
                <DropdownMenuItem className="flex cursor-pointer items-center gap-2" onClick={onView}>
                  <EyeIcon className="size-4" />
                  <span>View full frame</span>
                </DropdownMenuItem>
                {onShowInIncidents && (
                  <DropdownMenuItem className="flex cursor-pointer items-center gap-2" onClick={() => onShowInIncidents(incident)}>
                    <HistoryIcon className="size-4" />
                    <span>Show incident in Incidents</span>
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </TooltipProvider>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-1 overflow-hidden p-3">
        <div className="flex items-center justify-between gap-2 text-xs">
          <div className="flex items-center gap-1.5 font-semibold text-moss">
            <i className={`inline-block h-2 w-2 rounded-full ${KIND_COLOUR[item.itemType]}`} />
            <span className="uppercase tracking-[0.12em] text-[11px]">{KIND_LABEL[item.itemType]}</span>
          </div>
          <div className="flex items-center gap-1">
            <span className="font-mono text-[11px] text-ink-caption">{item.itemId}</span>
            {item.threatLevel != null && (
              <Badge variant="secondary" className="px-1.5 py-0 text-[10px]">
                Threat {item.threatLevel}
              </Badge>
            )}
          </div>
        </div>

        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <h3 className="line-clamp-1 text-[15px] font-semibold leading-snug tracking-tight text-ink">{item.name || item.label}</h3>
            </TooltipTrigger>
            <TooltipContent>{item.name || item.label}</TooltipContent>
          </Tooltip>
        </TooltipProvider>

        <p className="truncate text-[13px] leading-5 text-ink/60">{item.description}</p>
        <RelationshipLine relationship={relationship} />

        <div className="mt-auto flex items-center gap-2 border-t border-ink/8 pt-2 text-xs" data-no-card-nav>
          <IncidentThumbnail className="h-7 w-11 shrink-0 rounded" url={version?.thumbnailUrl} />
          <span className="min-w-0 flex-1 truncate text-ink/70">
            <strong className="font-semibold text-ink">{version?.title || incident.title || incident.incidentType}</strong>
            <span className="text-ink-caption">
              {version ? ` · ${version.isOfficial ? 'Official' : 'Latest'} v${version.revisionNo}` : ''}
            </span>
          </span>
          <SeverityChip level={incident.severityLevel} />
        </div>
      </div>
    </Card>
  );
}
