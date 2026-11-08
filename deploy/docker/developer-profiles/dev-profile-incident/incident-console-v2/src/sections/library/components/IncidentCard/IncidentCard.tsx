// SPDX-License-Identifier: Apache-2.0
'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { MoreHorizontalIcon, SearchIcon, TagIcon, Trash2Icon, WrenchIcon } from 'lucide-react';

import { cn } from 'cn';
import { Card } from '@/components/ui/card';
import { CARD_HOVER } from '@/lib/ui/card-hover';
import { ReportThumbnail } from '@/sections/library/components/ReportThumbnail';
import { DeleteIncidentDialog } from '@/sections/library/components/IncidentCard/DeleteIncidentDialog';
import type { ReportLibraryItem } from '@/modules/reports/domain/storage';
import { cardTitle } from '@/lib/library/view';
import { formatTimestamp } from '@/lib/time';
import { Button } from '@/components/ui/button';
import { NotOfficialPill, VersionPill } from '@/components/version-pill';
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
  onDelete,
  onOpen,
  onSearchEvidence,
}: {
  item: ReportLibraryItem;
  busy: boolean;
  onDelete: (item: ReportLibraryItem) => void;
  onOpen: (item: ReportLibraryItem) => void;
  onSearchEvidence: (item: ReportLibraryItem) => void;
}) {
  const router = useRouter();
  const [deleteOpen, setDeleteOpen] = useState(false);

  const href = `/reports/${encodeURIComponent(item.videoId)}?revision=${item.revisionId}`;
  const evidence = item.evidenceCount ?? 0;
  const displayTitle = cardTitle(item, `${item.incident_type} · ${formatTimestamp(item.uploadedAt)}`);

  function navigateToReport() {
    onOpen(item);
    router.push(href);
  }

  return (
    <>
      <Card
        data-card={item.revisionId}
        role="link"
        tabIndex={0}
        aria-label={`Open report: ${displayTitle}`}
        className={cn(
          'group relative flex cursor-pointer flex-col lg:h-full lg:max-h-[40vh] lg:min-h-0 gap-0 py-0 overflow-hidden rounded-xl border border-ink/10 bg-white p-0 shadow-xs focus-visible:outline-none',
          CARD_HOVER,
        )}
        id={`report-${item.revisionId}`}
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
          durationSeconds={item.durationSeconds}
          kind={item.kind}
          severity={item.severity}
          thumbnailUrl={item.thumbnailUrl}
          previewVideoId={item.videoId}
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
                  <DropdownMenuItem
                    className="flex cursor-pointer items-center gap-2"
                    disabled={evidence === 0}
                    onClick={() => onSearchEvidence(item)}
                  >
                    <SearchIcon className="size-4" />
                    <span>See evidence</span>
                    <span className="ml-auto text-xs text-ink/45">{evidence}</span>
                  </DropdownMenuItem>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem
                    className="flex cursor-pointer items-center gap-2 text-destructive focus:bg-destructive/10 focus:text-destructive"
                    onClick={() => setDeleteOpen(true)}
                    variant="destructive"
                  >
                    <Trash2Icon className="size-4" />
                    <span>Delete…</span>
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
              <span className="truncate">{item.incident_type}</span>
            </p>
            <div className="flex shrink-0 items-center gap-1" data-no-card-nav>
              <TooltipProvider>
                {item.outcome === 'valid_after_structural_repair' && (
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <span
                        className="inline-flex items-center gap-1 rounded-full border border-amber-300 bg-amber-50 px-1.5 py-0.5 text-[11px] font-bold text-amber-800"
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
                      <VersionPill data-testid="library-official-marker" kind={item.kind === 'human' ? 'human' : 'ai'} official />
                    </TooltipTrigger>
                    {item.officialSince && <TooltipContent>Made official {formatTimestamp(item.officialSince)}</TooltipContent>}
                  </Tooltip>
                ) : (
                  <>
                    <VersionPill kind={item.kind === 'human' ? 'human' : 'ai'} />
                    <NotOfficialPill data-testid="library-no-official-marker" />
                  </>
                )}
              </TooltipProvider>
            </div>
          </div>

          <h2 className="line-clamp-1 text-[15px] font-semibold leading-snug tracking-tight text-ink">{displayTitle}</h2>

          <p className="truncate text-[13px] leading-5 text-ink/60">{item.description}</p>
        </div>
      </Card>

      <DeleteIncidentDialog busy={busy} item={item} onConfirm={onDelete} onOpenChange={setDeleteOpen} open={deleteOpen} />
    </>
  );
}
