// SPDX-License-Identifier: Apache-2.0
'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { MoreHorizontalIcon, SearchIcon, StarIcon, TagIcon, Trash2Icon, VideoIcon, WrenchIcon } from 'lucide-react';

import { Card } from '@/components/ui/card';
import { ReportThumbnail } from '@/sections/library/components/ReportThumbnail';
import { DeleteIncidentDialog } from '@/sections/library/components/IncidentCard/DeleteIncidentDialog';
import type { LibraryIncident } from '@/sections/library/types';
import { cardTitle } from '@/lib/library/view';
import { formatTimestamp } from '@/lib/time';
import { Button } from '@/components/ui/button';
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';

export function IncidentCard({
  item,
  busy,
  waitingForDecision = false,
  onDelete,
  onOpen,
  onSearchEvidence,
}: {
  item: LibraryIncident;
  busy: boolean;
  /** A pending match suggestion names this incident. */
  waitingForDecision?: boolean;
  onDelete: (item: LibraryIncident) => void;
  onOpen: (item: LibraryIncident) => void;
  onSearchEvidence: (item: LibraryIncident) => void;
}) {
  const router = useRouter();
  const [deleteOpen, setDeleteOpen] = useState(false);

  const href = `/reports/${encodeURIComponent(item.incidentId)}${item.revisionId === null ? '' : `?revision=${item.revisionId}`}`;
  const versions = item.versionCount ?? 0;
  const noReport = item.revisionId === null;
  const waitingLabel = waitingForDecision ? 'Waiting for match decision' : 'No report yet';
  const displayTitle = noReport ? waitingLabel : cardTitle(item, `${item.incidentType} · ${formatTimestamp(item.uploadedAt)}`);

  const firstVideo = item.firstVideoName ?? 'No video';
  const videoLine = item.videoCount > 1 ? `${firstVideo} +${item.videoCount - 1} more` : firstVideo;
  const videoNames = item.videoCount > 1 ? `${firstVideo} and ${item.videoCount - 1} more` : firstVideo;

  function navigateToReport() {
    onOpen(item);
    router.push(href);
  }

  return (
    <>
      <Card
        data-card={item.incidentId}
        role="link"
        tabIndex={0}
        aria-label={`Open ${noReport ? 'incident' : 'report'}: ${displayTitle}`}
        className="group relative flex cursor-pointer flex-col lg:h-full lg:max-h-[40vh] lg:min-h-0 gap-0 py-0 overflow-hidden rounded-xl border border-ink/10 bg-white p-0 shadow-xs transition hover:border-ink/25 hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-moss"
        id={`report-${item.incidentId}`}
        onClick={(event) => {
          if (!event.currentTarget.contains(event.target as Node)) return;
          if ((event.target as HTMLElement).closest('[data-no-card-nav]')) return;
          navigateToReport();
        }}
        onKeyDown={(event) => {
          if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            navigateToReport();
          }
        }}
      >
        <ReportThumbnail
          alt={`Video screenshot for ${displayTitle}`}
          kind={item.kind ?? 'ai'}
          severity={item.severity}
          thumbnailUrl={item.thumbnailUrl}
          videoCount={item.videoCount}
        >
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
                        aria-label={`Actions for ${displayTitle}`}
                      >
                        <MoreHorizontalIcon className="size-4" />
                      </Button>
                    </DropdownMenuTrigger>
                  </TooltipTrigger>
                  <TooltipContent>More actions</TooltipContent>
                </Tooltip>
                <DropdownMenuContent
                  align="end"
                  className="w-52 bg-white"
                  onClick={(event) => event.stopPropagation()}
                  onPointerDown={(event) => event.stopPropagation()}
                >
                  <DropdownMenuItem className="flex cursor-pointer items-center gap-2" onClick={() => onSearchEvidence(item)}>
                    <SearchIcon className="size-4" />
                    <span>See evidence</span>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="flex cursor-pointer items-center gap-2 text-destructive focus:bg-destructive/10 focus:text-destructive"
                    onClick={() => setDeleteOpen(true)}
                    variant="destructive"
                  >
                    <Trash2Icon className="size-4" />
                    <span>Delete incident…</span>
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </TooltipProvider>
          </div>
        </ReportThumbnail>

        <div className="flex shrink-0 flex-col gap-1 overflow-hidden p-3">
          <div className="flex items-center justify-between gap-2">
            <p
              className="inline-flex min-w-0 items-center gap-1 rounded-md bg-moss/10 px-1.5 py-0.5 text-[11px] font-bold uppercase tracking-[0.08em] text-moss"
              data-testid="library-incident-type"
            >
              <TagIcon aria-hidden className="size-3 shrink-0" />
              <span className="sr-only">Incident type: </span>
              <span className="truncate">{noReport ? 'Waiting' : item.incidentType}</span>
            </p>
            <div className="flex shrink-0 items-center gap-1" data-no-card-nav>
              <TooltipProvider>
                {item.outcome === 'valid_after_structural_repair' && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span
                        className="inline-flex items-center gap-1 rounded-full border border-[#f3cc68] bg-[#fff1c7] px-1.5 py-0.5 text-[11px] font-bold text-[#765300]"
                        data-testid="library-repair-marker"
                      >
                        <WrenchIcon className="size-3" />
                      </span>
                    </TooltipTrigger>
                    <TooltipContent>Contract repair applied (IDs only)</TooltipContent>
                  </Tooltip>
                )}
                {item.isOfficial ? (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span
                        className="inline-flex items-center gap-1 rounded-full bg-moss px-2 py-0.5 text-[11px] font-bold text-white"
                        data-testid="library-official-marker"
                      >
                        <StarIcon className="size-3 fill-current" />
                        Official · {item.kind === 'human' ? 'Human' : 'AI'}
                      </span>
                    </TooltipTrigger>
                    {item.officialSince && <TooltipContent>Made official {formatTimestamp(item.officialSince)}</TooltipContent>}
                  </Tooltip>
                ) : noReport ? null : (
                  <span
                    className="inline-flex items-center rounded-full border border-dashed border-ink/30 bg-muted px-2 py-0.5 text-[11px] font-bold text-ink/60"
                    data-testid="library-no-official-marker"
                  >
                    No official version
                  </span>
                )}
              </TooltipProvider>
            </div>
          </div>

          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <h2 className="line-clamp-1 text-[15px] font-semibold leading-snug tracking-tight text-ink">{displayTitle}</h2>
              </TooltipTrigger>
              <TooltipContent>{displayTitle}</TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <p className="truncate text-[13px] leading-5 text-ink/60">
            {noReport
              ? waitingForDecision
                ? 'Decide the suggested match in the Matches tab; the report is built after.'
                : 'Open it to build the report.'
              : item.description}
          </p>

          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <p className="mt-1 flex min-w-0 items-center gap-1.5 text-xs font-medium text-ink/70" data-testid="video-name">
                  <VideoIcon className="size-3.5 shrink-0 text-ink/45" />
                  <span className="truncate">{videoLine}</span>
                </p>
              </TooltipTrigger>
              <TooltipContent>{videoNames}</TooltipContent>
            </Tooltip>
          </TooltipProvider>

          <p className="truncate text-xs text-ink/50">
            {item.videoCount} {item.videoCount === 1 ? 'video' : 'videos'} ·{' '}
            {noReport ? 'no report' : `${versions} ${versions === 1 ? 'version' : 'versions'}`} · Added {formatTimestamp(item.uploadedAt)}
          </p>
        </div>
      </Card>

      <DeleteIncidentDialog busy={busy} item={item} onConfirm={onDelete} onOpenChange={setDeleteOpen} open={deleteOpen} />
    </>
  );
}
