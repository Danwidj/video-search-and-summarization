// SPDX-License-Identifier: Apache-2.0
'use client';

import { PlayIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { evidenceDisplay } from '@/lib/evidence/evidence-view';
import { type EvidenceDetailItem, evidenceDetailLines } from '@/modules/reports/domain/evidence-detail';
import { EvidenceFrame, KIND_LABEL } from '@/sections/evidence/components/EvidenceFrame';

/**
 * One evidence item in detail: its whole frame with the box, large, the full description and Play from here, which closes
 * the pop-up and seeks the page's video to the item's second. Closes with Escape, the close button or a click outside.
 */
export function EvidenceDetailDialog({
  item,
  videoId,
  onClose,
  onPlayFrom,
}: {
  item: EvidenceDetailItem | null;
  /** The report's video; an older item's frame is cut from its stored file. */
  videoId: string;
  onClose: () => void;
  onPlayFrom: (seconds: number) => void;
}) {
  return (
    <Dialog open={item !== null} onOpenChange={(open) => !open && onClose()}>
      {item && <Detail item={item} onClose={onClose} onPlayFrom={onPlayFrom} videoId={videoId} />}
    </Dialog>
  );
}

function Detail({
  item,
  videoId,
  onClose,
  onPlayFrom,
}: {
  item: EvidenceDetailItem;
  videoId: string;
  onClose: () => void;
  onPlayFrom: (seconds: number) => void;
}) {
  const { seconds } = item;
  const lines = evidenceDetailLines(item);
  const shown = evidenceDisplay(item.evidence, videoId);
  return (
    <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto sm:max-w-3xl" data-testid="evidence-dialog">
      <DialogHeader className="pr-8">
        <DialogTitle className="flex items-center gap-2 text-lg">
          <Badge className="shrink-0 px-1.5 py-0 font-mono text-[10px] font-bold" variant="outline">
            {item.id}
          </Badge>
          <span className="min-w-0">{item.title}</span>
        </DialogTitle>
        <DialogDescription className="font-mono text-xs" data-testid="evidence-dialog-time">
          {KIND_LABEL[item.kind]}
          {lines.time && ` · most visible at ${lines.time}`}
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
          {lines.description}
        </p>
        {lines.holds && (
          <p>
            Holds <b>{lines.holds}</b>
          </p>
        )}
        {lines.heldBy && (
          <p>
            Held by <b>{lines.heldBy}</b>
          </p>
        )}
        {lines.threat && <p className="text-muted-foreground">{lines.threat}</p>}
        {lines.onScreen && <p className="text-muted-foreground">{lines.onScreen}</p>}
      </div>
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs text-muted-foreground">{lines.playNote}</p>
        <Button
          data-testid="evidence-dialog-play"
          disabled={seconds === null}
          onClick={() => {
            if (seconds === null) return;
            onClose();
            onPlayFrom(seconds);
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
