// SPDX-License-Identifier: Apache-2.0
'use client';

import { PlayIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import type { IncidentEvidenceItem } from '@/modules/reports/domain/incident-evidence';
import { evidenceDisplay, evidenceLabel } from '@/lib/evidence/evidence-view';
import { formatClock } from '@/modules/reports/domain/normalize';
import { EvidenceFrame } from '@/sections/evidence/components/EvidenceFrame';

/**
 * One evidence item in detail: its image large, the whole description, the video and time it comes from, and Play from here,
 * which opens that video at that time. Closes with Escape, the close button or a click outside.
 */
export function EvidenceDetailDialog({
  incidentId,
  item,
  onClose,
  onPlayFrom,
}: {
  incidentId: string;
  item: IncidentEvidenceItem | null;
  onClose: () => void;
  onPlayFrom: (video: string, seconds: number) => void;
}) {
  return (
    <Dialog open={item !== null} onOpenChange={(open) => !open && onClose()}>
      {item && <Detail incidentId={incidentId} item={item} onClose={onClose} onPlayFrom={onPlayFrom} />}
    </Dialog>
  );
}

function Detail({
  incidentId,
  item,
  onClose,
  onPlayFrom,
}: {
  incidentId: string;
  item: IncidentEvidenceItem;
  onClose: () => void;
  onPlayFrom: (video: string, seconds: number) => void;
}) {
  const { seconds } = item;
  const shown = evidenceDisplay(item.evidence, incidentId, item.video);
  const canPlay = seconds !== null && item.playable;
  return (
    <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-3xl" data-testid="evidence-dialog">
      <DialogHeader className="pr-8">
        <DialogTitle className="flex items-center gap-2 text-lg">
          <Badge className="shrink-0 px-1.5 py-0 font-mono text-[10px] font-bold" variant="outline">
            {evidenceLabel(item.video, item.id)}
          </Badge>
          <span className="min-w-0">{item.title}</span>
        </DialogTitle>
        <DialogDescription className="break-all font-mono text-xs" data-testid="evidence-dialog-source">
          {item.video}
          {seconds !== null && ` · ${formatClock(seconds)}`}
        </DialogDescription>
      </DialogHeader>
      <EvidenceFrame
        aspect={16 / 9}
        box={shown.box}
        frameSrc={shown.frameSrc}
        fullFrame
        kind={item.kind}
        label={`${item.title} image`}
        notLocated={shown.notLocated}
        seconds={seconds}
        src={shown.src}
      />
      <div className="grid gap-2 text-sm leading-6">
        <p className="whitespace-pre-wrap text-foreground/80" data-testid="evidence-dialog-description">
          {item.description || 'No description was recorded.'}
        </p>
        {item.holds.length > 0 && (
          <p>
            Holds <b>{item.holds.join(', ')}</b>
          </p>
        )}
        {item.holder && (
          <p>
            Held by <b>{item.holder}</b>
          </p>
        )}
        {item.lastHandledBy && (
          <p data-testid="evidence-last-handled-by">
            Last handled by <b>{item.lastHandledBy.who}</b>
            {item.lastHandledBy.seconds !== null && ` at ${formatClock(item.lastHandledBy.seconds)}`}
          </p>
        )}
        {item.kind === 'instrument' && (
          <p className="text-muted-foreground">
            Threat {item.threatLevel ?? 'unrated'}
            {item.threatLevel !== null ? '/5' : ''}
          </p>
        )}
        {item.onScreen && (
          <p className="text-muted-foreground">
            On screen {formatClock(item.onScreen.firstSeenSeconds)}–{formatClock(item.onScreen.lastSeenSeconds)}
          </p>
        )}
      </div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">
          {seconds === null
            ? 'No time was recorded for this item.'
            : item.playable
              ? null
              : 'This video was removed from the incident, so it cannot be played.'}
        </p>
        <Button
          data-testid="evidence-dialog-play"
          disabled={!canPlay}
          onClick={() => {
            if (!canPlay) return;
            onClose();
            onPlayFrom(item.video, seconds);
          }}
          type="button"
        >
          <PlayIcon />
          Play from here
        </Button>
      </div>
    </DialogContent>
  );
}
