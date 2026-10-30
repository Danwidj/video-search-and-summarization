// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { CheckIcon, CircleIcon, ClockIcon, MapPinIcon, TagIcon, VideoIcon, XIcon } from 'lucide-react';
import { cn } from 'cn';

import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { type ReasonGroup, reasonChipStyle } from '@/sections/suggestions/reason-chips';
import type { StructuredReason, SuggestionCard, SuggestionSide } from '@/sections/suggestions/types';

/** From 0.75 a match is strong; below that it is only possible. */
export function matchBand(score: number): { label: string; className: string } {
  return score >= 0.75 ? { label: 'Strong match', className: 'text-moss' } : { label: 'Possible match', className: 'text-amber-800' };
}

const videoLine = (side: SuggestionSide) => {
  const [first, ...rest] = side.videoNames;
  if (!first) return 'No videos';
  return rest.length ? `${first} +${rest.length} more` : first;
};

/** One incident of a pair: thumbnail, title, and its videos; opens the incident. */
export function SideLink({ side, className }: { side: SuggestionSide; className?: string }) {
  return (
    <Link
      className={cn(
        'group/side flex min-w-0 items-center gap-3 rounded-lg p-1.5 hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-signal',
        className,
      )}
      href={`/reports/${side.incidentId}`}
    >
      <span className="relative grid h-12 w-[5.25rem] shrink-0 place-items-center overflow-hidden rounded-md bg-[#dfe3dc] text-ink/30">
        {side.thumbnailUrl ? (
          // biome-ignore lint/performance/noImgElement: a presigned R2 URL that next/image would proxy and re-encode through the console server
          <img alt="" className="size-full object-cover" loading="lazy" src={side.thumbnailUrl} />
        ) : (
          <VideoIcon className="size-5" />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-sm font-semibold group-hover/side:underline">
          {side.title ?? `Incident #${side.incidentId}`}
        </span>
        <span className="block truncate text-xs text-muted-foreground">
          Incident {side.incidentId} · {videoLine(side)} · {side.videoNames.length} {side.videoNames.length === 1 ? 'video' : 'videos'}
        </span>
      </span>
    </Link>
  );
}

export function ScoreReadout({ score, compact = false }: { score: number; compact?: boolean }) {
  const band = matchBand(score);
  return (
    <div>
      <p className="flex items-baseline gap-2">
        <span className={cn('font-mono font-semibold tracking-tight', compact ? 'text-xl' : 'text-3xl')} data-testid="suggestion-score">
          {score.toFixed(2)}
          <span className="sr-only"> out of 1</span>
        </span>
        <span className={cn('text-xs font-semibold', band.className)}>{band.label}</span>
      </p>
      {compact ? null : <Progress aria-label="Score" className="mt-1.5 bg-primary/20" value={Math.round(score * 100)} />}
    </div>
  );
}

const CHIP_ICONS: Record<ReasonGroup, typeof CircleIcon> = { place: MapPinIcon, type: TagIcon, time: ClockIcon, other: CircleIcon };

/** One reason as a chip: place and event type are solid, time and differences are dashed hints. The detail is its tooltip. */
function ReasonChip({ reason }: { reason: StructuredReason }) {
  const { group, strong } = reasonChipStyle(reason.kind);
  const Icon = CHIP_ICONS[group];
  return (
    <span
      className={cn(
        'inline-flex h-5 w-fit shrink-0 items-center justify-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-xs font-medium [&>svg]:size-3',
        strong ? 'border-moss/20 bg-moss/10 font-semibold text-moss' : 'border-dashed border-ink/30 bg-white text-ink/60',
      )}
      data-kind={reason.kind}
      data-testid="suggestion-reason-chip"
      title={reason.detail || undefined}
    >
      <Icon aria-hidden />
      {reason.label}
    </span>
  );
}

/**
 * Why a pair matched. With the agent's structured reasons: chips, each with what was compared beside it
 * (`rows`) or in a list below (`chips`, for the banner, where the detail lines are `ReasonDetails`).
 * Without them (an older agent or an older stored row): the text reasons as plain lines.
 */
export function ReasonList({
  reasons,
  structuredReasons = [],
  layout = 'rows',
  className,
}: {
  reasons: string[];
  structuredReasons?: StructuredReason[];
  layout?: 'rows' | 'chips';
  className?: string;
}) {
  if (structuredReasons.length > 0) {
    if (layout === 'chips') {
      return (
        <ul aria-label="Reasons" className={cn('flex flex-wrap gap-1.5', className)} data-testid="suggestion-reasons">
          {structuredReasons.map((reason) => (
            <li key={reason.kind}>
              <ReasonChip reason={reason} />
            </li>
          ))}
        </ul>
      );
    }
    return (
      <ul className={cn('space-y-2', className)} data-testid="suggestion-reasons">
        {structuredReasons.map((reason) => (
          <li className="flex min-w-0 flex-col items-start gap-1 text-sm xl:flex-row xl:gap-2" key={reason.kind}>
            <span className="mt-0.5">
              <ReasonChip reason={reason} />
            </span>
            <span className={cn('pt-px text-[13px] leading-5', reasonChipStyle(reason.kind).strong ? 'text-ink/80' : 'text-ink/55')}>
              {reason.detail}
            </span>
          </li>
        ))}
      </ul>
    );
  }
  if (reasons.length === 0) return <p className={cn('text-sm text-muted-foreground', className)}>No reason was recorded.</p>;
  return (
    <ul className={cn('space-y-1.5', className)} data-testid="suggestion-reasons">
      {reasons.map((reason) => (
        <li className="text-[13px] leading-5 text-ink/80" key={reason}>
          {reason}
        </li>
      ))}
    </ul>
  );
}

/** The banner's detail lines under the chips: "Same place: what was compared". Nothing without structured reasons. */
export function ReasonDetails({ structuredReasons, className }: { structuredReasons: StructuredReason[]; className?: string }) {
  if (structuredReasons.length === 0) return null;
  return (
    <ul className={cn('space-y-1 border-t border-ink/10 pt-2.5', className)} data-testid="suggestion-reason-details">
      {structuredReasons.map((reason) => (
        <li className={cn('text-xs leading-5', reasonChipStyle(reason.kind).strong ? 'text-ink/75' : 'text-ink/50')} key={reason.kind}>
          <b className="font-semibold">{reason.label}</b>
          {reason.detail ? `: ${reason.detail}` : ''}
        </li>
      ))}
    </ul>
  );
}

export function DecisionButtons({
  card,
  busy,
  onAccept,
  onReject,
  small = false,
  className,
}: {
  card: SuggestionCard;
  busy: boolean;
  onAccept: (card: SuggestionCard) => void;
  onReject: (card: SuggestionCard) => void;
  small?: boolean;
  className?: string;
}) {
  const size = small ? 'sm' : 'default';
  return (
    <div className={cn('flex gap-2', className)}>
      <Button className="flex-1" data-testid="suggestion-accept" disabled={busy} onClick={() => onAccept(card)} size={size} type="button">
        <CheckIcon className="size-4" />
        Accept
      </Button>
      <Button
        className="flex-1"
        data-testid="suggestion-reject"
        disabled={busy}
        onClick={() => onReject(card)}
        size={size}
        type="button"
        variant="outline"
      >
        <XIcon className="size-4" />
        Reject
      </Button>
    </div>
  );
}
