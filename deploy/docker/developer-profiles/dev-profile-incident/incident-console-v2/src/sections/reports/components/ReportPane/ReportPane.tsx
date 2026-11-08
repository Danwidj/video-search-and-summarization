// SPDX-License-Identifier: Apache-2.0
'use client';

import { Fragment, type CSSProperties, type KeyboardEvent, type MouseEvent, type ReactNode, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { CARD_HOVER_STILL } from '@/lib/ui/card-hover';
import { EvidenceBadges } from '@/sections/reports/components/EvidenceBadges';
import { Button } from '@/components/ui/button';
import { VersionPill } from '@/components/version-pill';
import { Card as UICard, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { evidenceDisplay } from '@/lib/evidence/evidence-view';
import { severityStyle } from '@/lib/ui/severity';
import { cn } from '@/lib/utils';
import { formatClock } from '@/modules/reports/domain/normalize';
import {
  assetDetail,
  type EvidenceDetailItem,
  entityDetail,
  evidenceDetailLines,
  instrumentDetail,
} from '@/modules/reports/domain/evidence-detail';
import { reportHeading, type ReportView } from '@/modules/reports/domain/report-view';
import { STILL_BOX_COLOUR, type StillBox, type TrackedReportItem, stillBoxFor, trackedReportItems } from '@/modules/reports/domain/track';
import { EvidenceFrame } from '@/sections/evidence/components/EvidenceFrame';
import { EvidenceCarousel } from '@/sections/evidence/components/EvidenceCarousel';
import { EvidenceDetailDialog } from '@/sections/reports/components/EvidenceDetailDialog';
import { PresenceBar } from '@/sections/reports/components/PresenceBar';

const capitalize = (value: string | null) => (value ? value[0].toUpperCase() + value.slice(1) : 'Unclassified');

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 border-b border-border/70 py-2 last:border-b-0 sm:grid-cols-[6.5rem_minmax(0,1fr)] sm:gap-4">
      <dt className="pt-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</dt>
      <dd className="m-0 min-w-0 text-sm leading-snug text-foreground">{children}</dd>
    </div>
  );
}

/**
 * The scrolling part of View mode: the version, its report fields, its evidence grouped by holder (each card opens in
 * detail, and also selects the item's box in the player; a tracked item's card shows where it is on screen), and the model's own output.
 */
export function ReportPane({
  report,
  playerDuration,
  onSeek,
  officialMissing = false,
  selectedTrackId = null,
  onSelectTrack = () => undefined,
}: {
  report: ReportView;
  playerDuration: number | null;
  onSeek: (seconds: number, still?: StillBox | null) => void;
  /** True once the versions have loaded and none of them is official. */
  officialMissing?: boolean;
  /** The item whose box the player emphasises; null for none. */
  selectedTrackId?: string | null;
  onSelectTrack?: (id: string | null) => void;
}) {
  const { structured, modelOutput, run, differences, revision } = report;
  const { incident } = structured;
  const heldBy = (entityId: string) => structured.instruments.filter((instrument) => instrument.entityId === entityId);
  const heldIds = new Set(structured.entities.flatMap((entity) => heldBy(entity.entityId).map((instrument) => instrument.instrumentId)));
  const unheld = structured.instruments.filter((instrument) => !heldIds.has(instrument.instrumentId));
  const [detail, setDetail] = useState<EvidenceDetailItem | null>(null);
  const [carouselControlsTarget, setCarouselControlsTarget] = useState<HTMLElement | null>(null);
  const itemCount = structured.entities.length + structured.instruments.length + structured.assets.length;
  const tracked = new Map(trackedReportItems(structured).map((item) => [`${item.kind}:${item.id}`, item]));
  const cardProps = (item: EvidenceDetailItem) => {
    const track = tracked.get(`${item.kind}:${item.id}`) ?? null;
    const hasBox = track !== null || stillBoxFor(item) !== null;
    return {
      item,
      track,
      playerDuration,
      selected: hasBox && selectedTrackId === item.id,
      onOpen: setDetail,
      onSeek,
      // Opening the card also selects its box in the player.
      onSelect: hasBox ? (toggle: boolean) => onSelectTrack(toggle && selectedTrackId === item.id ? null : item.id) : undefined,
      videoId: report.videoId,
    };
  };

  return (
    <div className="px-5 pb-16 sm:px-8">
      <UICard className="mt-5 gap-0 border-border/80 py-0" data-testid="report-fields-section">
        <CardHeader className="gap-1 border-b border-l-4 border-border/70 border-l-primary bg-primary/5 px-4 py-3.5">
          <CardTitle className="text-base font-semibold">Report fields</CardTitle>
        </CardHeader>
        <CardContent className="px-4 pb-3 pt-1">
          {run.status === 'valid_after_structural_repair' && (
            <p className="mb-2 px-4 py-2 text-xs text-amber-800" data-testid="contract-repair-applied">
              Contract repair applied (IDs only)
            </p>
          )}
          {run.notesKind === 'legacy' && <p className="mb-2 px-4 py-2 text-xs text-muted-foreground">Earlier prompt version</p>}
          {officialMissing && (
            <p
              className="mb-2 border-b border-dashed border-not-official-line bg-not-official-pill/60 px-4 py-2 text-xs text-ink-caption"
              data-testid="official-status"
            >
              No official version has been selected for this video. Star a version to make it official.
            </p>
          )}
          <dl className="m-0">
            <Row label="Title">
              <div className="flex items-start justify-between gap-3">
                <span>{reportHeading(report)}</span>
                <span className="flex shrink-0 flex-wrap items-center justify-end gap-1.5">
                  <VersionPill kind={revision.kind === 'human' ? 'human' : 'ai'} official={report.official.isOfficial} />
                  {incident.confidenceScore !== null && (
                    <Badge className="font-mono text-[11px]" data-testid="confidence-tag" variant="secondary">
                      {Math.round(incident.confidenceScore * 100)}% confidence
                    </Badge>
                  )}
                </span>
              </div>
              {modelOutput?.title && modelOutput.title !== reportHeading(report) && (
                <span className="mt-0.5 block text-xs text-muted-foreground/80" data-testid="title-edited">
                  Set by a reviewer. The model&apos;s title: {modelOutput.title}
                </span>
              )}
            </Row>
            <Row label="Incident type">
              {capitalize(incident.type)}
              {modelOutput?.location ? ` · ${modelOutput.location}` : ''}
              {differences.type && (
                <span className="mt-0.5 block text-xs font-semibold text-destructive" data-testid="type-edited">
                  Model classified this as {differences.type.model}; reviewer set {differences.type.current}.
                </span>
              )}
            </Row>
            <Row label="Severity">
              <Badge className={`px-3 py-0.5 text-xs font-bold ${severityStyle(incident.severityLevel)}`} variant="outline">
                {incident.severityLevel ?? '—'}/5
              </Badge>
            </Row>
            <Row label="Time range">
              {incident.startSeconds !== null ? (
                <Button
                  className="h-6 font-mono text-xs font-bold"
                  onClick={() => onSeek(incident.startSeconds ?? 0)}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  {formatClock(incident.startSeconds)}
                  {incident.endSeconds !== null ? `–${formatClock(incident.endSeconds)}` : ''}
                </Button>
              ) : (
                'Not recorded'
              )}
            </Row>
            <Row label="Summary">
              <span className="whitespace-pre-wrap">{incident.description ?? 'No summary was recorded.'}</span>
            </Row>
            <Row label="Severity rationale">
              <span className="text-foreground/75">
                {incident.severityReason ?? modelOutput?.severityReason ?? 'No severity rationale was recorded.'}
              </span>
            </Row>
          </dl>
        </CardContent>
      </UICard>

      <UICard className="mt-5 gap-0 overflow-hidden border-border/80 py-0" data-testid="evidence-section">
        <CardHeader className="flex flex-row items-center justify-between gap-4 border-b border-l-4 border-border/70 border-l-primary bg-primary/5 px-4 py-2">
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
            <CardTitle className="text-base font-semibold">Evidence items</CardTitle>
            <Badge className="font-mono text-[10px]" variant="secondary">
              {itemCount}
            </Badge>
            <CardDescription className="text-xs">People, instruments and assets linked to this incident</CardDescription>
          </div>
          <nav aria-label="Evidence navigation" className="flex min-h-8 shrink-0 gap-2" ref={setCarouselControlsTarget} />
        </CardHeader>
        {itemCount === 0 ? (
          <CardContent className="px-4 py-5">
            <p
              className="m-0 rounded-lg border border-dashed border-border px-4 py-5 text-center text-sm text-muted-foreground"
              data-testid="evidence-empty"
            >
              No evidence items yet. Use Edit to add people, instruments or assets to this incident.
            </p>
          </CardContent>
        ) : (
          <div className="px-4 pt-3 pb-1" data-testid="evidence-grid">
            <EvidenceCarousel controlsTarget={carouselControlsTarget} label="Report evidence items">
              {structured.entities.map((entity) => (
                <Fragment key={entity.entityId}>
                  <Card {...cardProps(entityDetail(entity, structured.instruments))} />
                  {heldBy(entity.entityId).map((instrument) => (
                    <Card key={instrument.instrumentId} {...cardProps(instrumentDetail(instrument, structured.entities))} />
                  ))}
                </Fragment>
              ))}
              {unheld.map((instrument) => (
                <Card key={instrument.instrumentId} {...cardProps(instrumentDetail(instrument, structured.entities))} />
              ))}
              {structured.assets.map((asset) => (
                <Card key={asset.assetId} {...cardProps(assetDetail(asset))} />
              ))}
            </EvidenceCarousel>
          </div>
        )}
      </UICard>

      <EvidenceDetailDialog
        item={detail}
        onClose={() => setDetail(null)}
        onPlayFrom={onSeek}
        playerDuration={playerDuration}
        track={detail ? (tracked.get(`${detail.kind}:${detail.id}`) ?? null) : null}
        videoId={report.videoId}
      />
    </div>
  );
}

/** The canonical id (E1, I1, A1) that Edit and Compare print for the same item. */
function IdBadge({ id }: { id: string }) {
  return (
    <Badge className="shrink-0 px-1.5 py-0 font-mono text-[10px] font-bold" data-testid="evidence-id" variant="outline">
      {id}
    </Badge>
  );
}

/**
 * One evidence item: its whole video frame with the box drawn on it (never a cut-out crop). The whole card is a button
 * (click, Enter or Space) that opens the item in detail and selects its box in the player; a tracked item's card also shows
 * its presence bar, whose own buttons seek without opening it.
 */
function Card({
  item,
  track,
  playerDuration,
  selected,
  videoId,
  onOpen,
  onSeek,
  onSelect,
}: {
  item: EvidenceDetailItem;
  track: TrackedReportItem | null;
  playerDuration: number | null;
  selected: boolean;
  videoId: string;
  onOpen: (item: EvidenceDetailItem) => void;
  onSeek: (seconds: number) => void;
  onSelect?: (toggle: boolean) => void;
}) {
  const { seconds } = item;
  const lines = evidenceDetailLines(item);
  const shown = evidenceDisplay(item.evidence, videoId);
  // Opening the card also selects its box in the player; inner buttons and links keep their own action.
  const open = () => {
    onOpen(item);
    onSelect?.(false);
  };
  return (
    <UICard
      aria-label={`Show ${item.title} in detail`}
      className={cn(
        'w-88 max-w-full shrink-0 snap-start gap-0 overflow-hidden py-0 text-xs focus-visible:outline-none',
        CARD_HOVER_STILL,
        selected && 'ring-2 ring-ring',
      )}
      data-selected={selected ? 'true' : undefined}
      data-testid="evidence-card"
      data-track-item={track?.id}
      onClick={(event: MouseEvent<HTMLDivElement>) => {
        if ((event.target as HTMLElement).closest('button, a')) return;
        open();
      }}
      onKeyDown={(event: KeyboardEvent<HTMLDivElement>) => {
        if (event.target !== event.currentTarget || (event.key !== 'Enter' && event.key !== ' ')) return;
        event.preventDefault();
        open();
      }}
      role="button"
      style={
        selected
          ? ({
              '--tw-ring-color': track?.colour ?? STILL_BOX_COLOUR,
            } as CSSProperties)
          : undefined
      }
      tabIndex={0}
    >
      <div data-testid="evidence-open">
        <EvidenceFrame
          aspect={16 / 9}
          box={shown.box}
          boxColour={track?.colour ?? STILL_BOX_COLOUR}
          className="rounded-none!"
          frameSrc={shown.frameSrc}
          fullFrame
          kind={item.kind}
          label={item.title}
          notLocated={shown.notLocated}
          seconds={seconds}
          src={shown.src}
        />
      </div>
      <CardHeader className="gap-0 border-b border-border/70 bg-primary/5 px-3 py-2.5">
        <CardTitle className="flex items-center gap-2 text-sm font-semibold">
          <IdBadge id={item.id} />
          <span className="min-w-0">{item.title}</span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-1 p-3">
        <EvidenceBadges badges={lines.badges} />
        <p className="text-muted-foreground">{item.description}</p>
        {lines.holds && (
          <p>
            Holds <b>{lines.holds}</b>
          </p>
        )}
        {lines.threat && <p className="text-muted-foreground">{lines.threat}</p>}
        {lines.heldBy && (
          <p>
            Held by <b>{lines.heldBy}</b>
          </p>
        )}
        {lines.onScreen && <p className="text-muted-foreground">{lines.onScreen}</p>}
        {lines.notTracked && (
          <p className="text-xs text-muted-foreground" data-testid="evidence-not-tracked">
            {lines.notTracked}
          </p>
        )}
        {lines.time && (
          <p className="text-muted-foreground">
            Most visible at <b className="font-mono">{lines.time}</b>
          </p>
        )}
        {track && (
          <PresenceBar
            colour={track.colour}
            durationSeconds={playerDuration}
            firstSeconds={track.firstSeconds}
            label={item.title}
            lastSeconds={track.lastSeconds}
            onSeek={onSeek}
          />
        )}
      </CardContent>
    </UICard>
  );
}
