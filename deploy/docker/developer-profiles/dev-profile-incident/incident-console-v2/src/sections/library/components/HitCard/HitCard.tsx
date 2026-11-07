// SPDX-License-Identifier: Apache-2.0
'use client';

import { useRouter } from 'next/navigation';

import { cn } from 'cn';
import { Card } from '@/components/ui/card';
import { CARD_HOVER, CARD_ZOOM } from '@/lib/ui/card-hover';
import { Badge } from '@/components/ui/badge';
import { EvidenceFrame, KIND_COLOUR } from '@/sections/evidence/components/EvidenceFrame';
import { SeverityChip } from '@/sections/library/components/Shared';
import { KIND_NAME, type SearchedVersion, hitTitle, matchPercent, reportHref } from '@/lib/library/search';
import type { EvidenceSearchHit } from '@/modules/search/domain/search';
import { formatClock } from '@/modules/reports/domain/normalize';
import { hitDisplay } from '@/lib/evidence/evidence-view';

/** One evidence hit. The whole card opens the incident's report at the evidence: the second the box was found at. */
export function HitCard({
  hit,
  version,
  showMatch = true,
}: {
  hit: EvidenceSearchHit;
  version?: SearchedVersion;
  /** False for a listing with no query, which has no similarity to show. */
  showMatch?: boolean;
}) {
  const router = useRouter();
  const { item, incident } = hit;
  const href = reportHref(hit, version);
  const clock = formatClock(item.timestampSeconds);
  const title = hitTitle(item);
  const shown = hitDisplay(item, incident.videoId);
  const videoLine = [version?.filename, version ? `${version.isOfficial ? 'Official' : 'Latest'} v${version.revisionNo}` : '']
    .filter(Boolean)
    .join(' · ');

  return (
    <Card
      data-testid="evidence-hit"
      role="link"
      tabIndex={0}
      aria-label={`Open report at ${clock}: ${title}`}
      className={cn(
        'group relative flex cursor-pointer flex-col overflow-hidden rounded-xl border border-ink/10 bg-white p-0 shadow-xs focus-visible:outline-none',
        CARD_HOVER,
      )}
      onClick={() => router.push(href)}
      onKeyDown={(event) => {
        if (event.target === event.currentTarget && (event.key === 'Enter' || event.key === ' ')) {
          event.preventDefault();
          router.push(href);
        }
      }}
    >
      <div className="relative aspect-video shrink-0 overflow-hidden bg-black">
        <div className={cn('h-full w-full', CARD_ZOOM)}>
          <EvidenceFrame
            aspect={16 / 9}
            box={shown.box}
            className="h-full w-full rounded-none !bg-black"
            drawBox
            frameSrc={shown.frameSrc}
            fullFrame
            kind={item.itemType}
            label={title}
            notLocated={shown.notLocated}
            src={shown.src}
          />
        </div>

        <Badge
          variant="outline"
          className="absolute left-2.5 top-2.5 h-auto rounded-full border border-ink/10 bg-white px-2 py-0.5 text-[11px] font-bold text-ink shadow-xs"
          data-testid="hit-match"
        >
          {showMatch ? `${matchPercent(hit)}% match` : 'In incident'}
        </Badge>

        <span className="absolute bottom-2 left-2.5 rounded bg-ink/80 px-1.5 py-0.5 font-mono text-[11px] text-white">{clock}</span>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-1 p-3">
        <div className="flex min-w-0 items-center gap-2">
          <span
            className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-ink/10 bg-[#f7f8f4] px-[7px] py-px text-[11.5px] font-semibold text-moss"
            data-testid="hit-kind"
          >
            <i className={`inline-block h-2 w-2 rounded-full ${KIND_COLOUR[item.itemType]}`} />
            {KIND_NAME[item.itemType]}
          </span>
          <h3 className="min-w-0 flex-1 truncate text-[15px] font-semibold leading-snug tracking-tight text-ink" title={title}>
            {title}
          </h3>
          {item.threatLevel != null && (
            <Badge variant="secondary" className="shrink-0 px-1.5 py-0 text-[10px]">
              Threat {item.threatLevel}
            </Badge>
          )}
        </div>

        <p className="line-clamp-2 text-[13px] leading-5 text-ink/60">{item.description}</p>

        <div className="mt-auto flex items-center gap-2 border-t border-ink/8 pt-2 text-xs">
          <span className="min-w-0 flex-1 text-ink/70">
            <strong className="block truncate font-semibold text-ink">{version?.title || incident.title || incident.incidentType}</strong>
            {videoLine && <span className="mt-0.5 block truncate font-mono text-[11px] text-ink-caption">{videoLine}</span>}
          </span>
          <SeverityChip level={incident.severityLevel} />
        </div>
      </div>
    </Card>
  );
}
