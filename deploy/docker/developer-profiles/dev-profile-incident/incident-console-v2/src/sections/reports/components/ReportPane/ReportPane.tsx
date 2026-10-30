// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { type ReactNode, useState } from 'react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card as UICard, CardContent } from '@/components/ui/card';
import { evidenceDisplay } from '@/lib/evidence/evidence-view';
import { formatTimestamp } from '@/lib/time';
import { severityStyle } from '@/lib/ui/severity';
import { timestampWithinVideo } from '@/modules/contract/domain/video-bounds';
import { formatClock } from '@/modules/reports/domain/normalize';
import {
  assetDetail,
  type EvidenceDetailItem,
  entityDetail,
  evidenceDetailLines,
  instrumentDetail,
} from '@/modules/reports/domain/evidence-detail';
import { reportHeading, type ReportView } from '@/modules/reports/domain/report-view';
import { EvidenceFrame } from '@/sections/evidence/components/EvidenceFrame';
import { EvidenceDetailDialog } from '@/sections/reports/components/EvidenceDetailDialog';
import { RunDetailsPanel } from '@/sections/reports/components/ReportRunDetails';

const capitalize = (value: string | null) => (value ? value[0].toUpperCase() + value.slice(1) : 'Unclassified');

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid gap-1 border-b border-border py-3 sm:grid-cols-[8rem_1fr] sm:gap-6">
      <dt className="pt-0.5 font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-muted-foreground">{label}</dt>
      <dd className="m-0 text-sm leading-6 text-foreground/80">{children}</dd>
    </div>
  );
}

/** The scrolling part of View mode: the version, its report fields, its evidence grouped by holder (each card opens in detail), and the model's own output. */
export function ReportPane({
  report,
  playerDuration,
  onSeek,
  officialMissing = false,
  compareHref = null,
}: {
  report: ReportView;
  playerDuration: number | null;
  onSeek: (seconds: number) => void;
  /** True once the versions have loaded and none of them is official. */
  officialMissing?: boolean;
  /** Link to compare this version with another AI version, when there is one. */
  compareHref?: string | null;
}) {
  const { structured, modelOutput, run, differences, revision } = report;
  const { incident } = structured;
  const windowEdited = differences.fields.includes('incident window');
  const original = modelOutput?.original;
  const heldBy = (entityId: string) => structured.instruments.filter((instrument) => instrument.entityId === entityId);
  const heldIds = new Set(structured.entities.flatMap((entity) => heldBy(entity.entityId).map((instrument) => instrument.instrumentId)));
  const unheld = structured.instruments.filter((instrument) => !heldIds.has(instrument.instrumentId));
  const [detail, setDetail] = useState<EvidenceDetailItem | null>(null);
  const itemCount = structured.entities.length + structured.instruments.length + structured.assets.length;

  return (
    <div className="px-5 pb-16 sm:px-8">
      <UICard className="mt-5 gap-0 border-border bg-muted/40 py-0 text-sm" data-testid="version-summary">
        <CardContent className="divide-y divide-border p-0">
          <div className="px-4 py-3">
            <p className="flex flex-wrap items-center gap-2" data-testid="revision-label">
              <b>v{revision.revisionNo}</b>
              <Badge className="px-2 py-0.5 text-[11px] font-semibold" variant="secondary">
                {revision.kind === 'human' ? 'Human' : 'AI'}
              </Badge>
              {revision.kind === 'ai' && <span className="text-muted-foreground">{run.model}</span>}
              {report.official.isOfficial && (
                <Badge
                  className="border-amber-400 bg-amber-50 text-[11px] font-bold text-amber-800"
                  data-testid="official-status"
                  variant="outline"
                >
                  ★ Official
                </Badge>
              )}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              {formatTimestamp(revision.createdAt, 'time unknown')}
              {revision.note ? ` · ${revision.note}` : ''}
            </p>
          </div>
          {run.status === 'valid_after_structural_repair' && (
            <p className="px-4 py-2 text-xs text-amber-800" data-testid="contract-repair-applied">
              Contract repair applied (IDs only)
            </p>
          )}
          {run.notesKind === 'legacy' && <p className="px-4 py-2 text-xs text-muted-foreground">Earlier prompt version</p>}
          {officialMissing && (
            <p className="bg-amber-50/80 px-4 py-2 text-xs text-amber-950" data-testid="official-status">
              No official version has been selected for this video. Star a version to make it official.
            </p>
          )}
          {compareHref && (
            <p className="px-4 py-2 text-xs">
              <span className="text-muted-foreground">Another AI version is available for this video. </span>
              <Link
                className="font-semibold text-primary hover:underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-hidden"
                href={compareHref}
              >
                Compare versions side by side →
              </Link>
            </p>
          )}
        </CardContent>
      </UICard>

      <h3 className="mt-6 font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-muted-foreground">Report fields</h3>
      <dl className="m-0">
        <Row label="Title">
          {reportHeading(report)}
          {modelOutput?.title && (
            <span className="mt-0.5 block text-xs text-muted-foreground/80">
              Title generated by the model{differences.fields.length ? ' (before reviewer edits)' : ''}
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
          {differences.severity && (
            <span className="mt-1 block text-xs font-semibold text-destructive" data-testid="severity-edited">
              Model assessed severity {differences.severity.model}/5; reviewer set {differences.severity.current}/5. The rationale below
              explains the model&apos;s assessment, not the reviewer&apos;s.
            </span>
          )}
        </Row>
        {incident.confidenceScore !== null && <Row label="Confidence">{Math.round(incident.confidenceScore * 100)}%</Row>}
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
          {windowEdited && original && original.startSeconds !== null && original.endSeconds !== null && (
            <span className="ml-3 text-xs font-semibold text-destructive" data-testid="window-edited">
              reviewer-set; model window {formatClock(original.startSeconds)}–{formatClock(original.endSeconds)}
            </span>
          )}
        </Row>
        <Row label="Summary">
          <span className="whitespace-pre-wrap">{incident.description ?? 'No summary was recorded.'}</span>
        </Row>
        <Row label="Severity rationale">
          <span className="text-foreground/75">{modelOutput?.severityReason ?? 'No model rationale was retained for this run.'}</span>
          {differences.severity && (
            <span className="mt-0.5 block text-xs text-muted-foreground">For model severity {differences.severity.model}/5</span>
          )}
        </Row>
      </dl>
      {differences.fields.length > 0 && (
        <Badge className="mt-3 text-xs font-semibold text-destructive" data-testid="reviewer-edited" variant="secondary">
          Reviewer-edited after generation: {differences.fields.join(', ')}
        </Badge>
      )}

      <h3 className="mt-7 font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-muted-foreground">
        Evidence items · {itemCount}
      </h3>
      {itemCount === 0 ? (
        <p className="mt-2 text-sm italic text-muted-foreground" data-testid="evidence-empty">
          This version has no evidence items.
        </p>
      ) : (
        <div className="mt-2 space-y-4" data-testid="evidence-grid">
          {structured.entities.map((entity) => (
            <div className="grid gap-3 sm:grid-cols-[6rem_1fr]" data-holder={entity.entityId} key={entity.entityId}>
              <span className="font-mono text-[10.5px] font-bold uppercase tracking-wider text-muted-foreground">Entity</span>
              <div className="flex flex-wrap gap-3">
                <Card item={entityDetail(entity, structured.instruments)} onOpen={setDetail} videoId={report.videoId} />
                {heldBy(entity.entityId).map((instrument) => (
                  <Card
                    item={instrumentDetail(instrument, structured.entities)}
                    key={instrument.instrumentId}
                    onOpen={setDetail}
                    videoId={report.videoId}
                  />
                ))}
              </div>
            </div>
          ))}
          {unheld.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-[6rem_1fr]" data-holder="unknown">
              <span className="font-mono text-[10.5px] font-bold uppercase tracking-wider text-muted-foreground">Holder unknown</span>
              <div className="flex flex-wrap gap-3">
                {unheld.map((instrument) => (
                  <Card
                    item={instrumentDetail(instrument, structured.entities)}
                    key={instrument.instrumentId}
                    onOpen={setDetail}
                    videoId={report.videoId}
                  />
                ))}
              </div>
            </div>
          )}
          {structured.assets.length > 0 && (
            <div className="grid gap-3 sm:grid-cols-[6rem_1fr]" data-holder="assets">
              <span className="font-mono text-[10.5px] font-bold uppercase tracking-wider text-muted-foreground">Assets</span>
              <div className="flex flex-wrap gap-3">
                {structured.assets.map((asset) => (
                  <Card item={assetDetail(asset)} key={asset.assetId} onOpen={setDetail} videoId={report.videoId} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <EvidenceDetailDialog item={detail} onClose={() => setDetail(null)} onPlayFrom={onSeek} videoId={report.videoId} />

      <ModelSection title="Model event timeline" source={modelOutput?.source}>
        {windowEdited && original && original.startSeconds !== null && original.endSeconds !== null && (
          <p className="mb-2 text-[11px] text-destructive">
            Event times are the model&apos;s, relative to its original window {formatClock(original.startSeconds)}–
            {formatClock(original.endSeconds)}.
          </p>
        )}
        {modelOutput && !modelOutput.timelineCheck.consistentWithWindow && (
          <Alert className="mb-2 border-amber-300 bg-amber-50/80 p-3 text-xs leading-5 text-amber-950" data-testid="timeline-inconsistent">
            <AlertDescription>
              Model-generated timeline, not consistent with the detected incident window
              {original && original.startSeconds !== null && original.endSeconds !== null
                ? ` (${formatClock(original.startSeconds)}–${formatClock(original.endSeconds)})`
                : ''}
              . Events outside the window are the model&apos;s context, not incident timestamps. The timeline is not scored and does not
              affect the report&apos;s validity.
            </AlertDescription>
          </Alert>
        )}
        {modelOutput?.timeline.length ? (
          <ol className="space-y-2">
            {modelOutput.timeline.map((event) => {
              const clock = `${formatClock(event.startSeconds)}${event.endSeconds !== null && event.endSeconds !== event.startSeconds ? `–${formatClock(event.endSeconds)}` : ''}`;
              const outsideWindow = event.insideWindow === false;
              const seekable =
                event.seekable !== false && (playerDuration === null || timestampWithinVideo(event.startSeconds, playerDuration));
              const tags = (
                <>
                  {outsideWindow && (
                    <Badge
                      className="text-[10px] font-semibold uppercase tracking-wide"
                      data-testid="event-outside-window"
                      variant="secondary"
                    >
                      outside incident window
                    </Badge>
                  )}
                  {!seekable && (
                    <Badge
                      className="text-[10px] font-semibold uppercase tracking-wide"
                      data-testid="event-outside-video"
                      variant="destructive"
                    >
                      outside the video
                    </Badge>
                  )}
                </>
              );
              return (
                <li key={`${event.startSeconds}-${event.endSeconds ?? ''}-${event.description}`}>
                  {seekable ? (
                    <button
                      aria-label={`Play video from ${formatClock(event.startSeconds)}: ${event.description}`}
                      className={`group flex w-full gap-4 rounded-xl border p-3 text-left transition hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring ${outsideWindow ? 'border-dashed border-border' : 'border-border'}`}
                      onClick={() => onSeek(event.startSeconds)}
                      type="button"
                    >
                      <span
                        className={`whitespace-nowrap font-mono text-xs font-bold ${outsideWindow ? 'text-muted-foreground' : 'text-primary'}`}
                      >
                        {clock}
                      </span>
                      <span className={`text-sm leading-5 ${outsideWindow ? 'text-muted-foreground' : 'text-foreground/80'}`}>
                        {event.description} {tags}
                      </span>
                    </button>
                  ) : (
                    <div
                      className="flex w-full gap-4 rounded-xl border border-dashed border-border p-3 text-left"
                      data-testid="event-not-seekable"
                    >
                      <span className="whitespace-nowrap font-mono text-xs font-bold text-muted-foreground">{clock}</span>
                      <span className="text-sm leading-5 text-muted-foreground">
                        {event.description} {tags}
                      </span>
                    </div>
                  )}
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="rounded-xl border border-dashed border-border p-4 text-sm text-muted-foreground">
            {modelOutput ? 'The model returned no timestamped events.' : 'The original model output was not retained for this run.'}
          </p>
        )}
      </ModelSection>

      {modelOutput && modelOutput.uncertainties.length > 0 && (
        <ModelSection title="Model-reported uncertainties" source={modelOutput.source}>
          <ul className="space-y-2 text-sm leading-5 text-foreground/75">
            {modelOutput.uncertainties.map((item) => (
              <li className="border-l-2 border-primary/40 pl-3" key={item}>
                {item}
              </li>
            ))}
          </ul>
        </ModelSection>
      )}

      <div className="-mx-5 mt-6 sm:-mx-8">
        <RunDetailsPanel report={report} />
      </div>
    </div>
  );
}

function ModelSection({ title, source, children }: { title: string; source?: 'contract' | 'legacy'; children: ReactNode }) {
  return (
    <section className="mt-7">
      <h3 className="font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-muted-foreground">{title}</h3>
      <p className="mb-3 mt-1 text-[11px] text-muted-foreground/70">
        Original model output · read-only{source === 'legacy' ? ' · earlier prompt version' : ''}
      </p>
      {children}
    </section>
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

/** One evidence item: its whole video frame with the box drawn on it (never a cut-out crop), which opens the item in detail. */
function Card({ item, videoId, onOpen }: { item: EvidenceDetailItem; videoId: string; onOpen: (item: EvidenceDetailItem) => void }) {
  const { seconds } = item;
  const lines = evidenceDetailLines(item);
  const shown = evidenceDisplay(item.evidence, videoId);
  return (
    <UICard className="w-64 max-w-full overflow-hidden text-xs" data-testid="evidence-card">
      <button
        aria-label={`Show ${item.title} in detail`}
        className="block w-full cursor-zoom-in focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-testid="evidence-open"
        onClick={() => onOpen(item)}
        type="button"
      >
        <EvidenceFrame
          aspect={16 / 9}
          box={shown.box}
          className="rounded-none!"
          frameSrc={shown.frameSrc}
          fullFrame
          kind={item.kind}
          label={item.title}
          notLocated={shown.notLocated}
          seconds={seconds}
          src={shown.src}
        />
      </button>
      <CardContent className="space-y-1 p-3">
        <h4 className="flex items-center gap-2 text-sm font-semibold">
          <IdBadge id={item.id} />
          <span className="min-w-0">{item.title}</span>
        </h4>
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
        {lines.time && (
          <p className="text-muted-foreground">
            Most visible at <b className="font-mono">{lines.time}</b>
          </p>
        )}
      </CardContent>
    </UICard>
  );
}
