// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { EvidenceFrame, KIND_LABEL } from '@/sections/evidence/components/EvidenceFrame';
import { FrameViewer } from '@/sections/evidence/components/FrameViewer';
import { RelationshipLine } from '@/sections/library/components/HitCard';
import { type SearchedVersion, hitKey, hitsInFrame, matchPercent, relationshipOf, reportHref } from '@/lib/library/search';
import type { EvidenceSearchHit } from '@/modules/search/domain/search';
import { formatClock } from '@/modules/reports/domain/normalize';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

/** The modal opened from any crop: the item's frame with every box found at that moment, its details and a way into the report at that time. */
export function HitViewer({
  hit,
  hits,
  versions,
  onClose,
  showMatch = true,
}: {
  hit: EvidenceSearchHit;
  hits: EvidenceSearchHit[];
  versions: Record<string, SearchedVersion>;
  onClose: () => void;
  /** False for a listing with no query, which has no similarity to show. */
  showMatch?: boolean;
}) {
  const [selectedKey, setSelectedKey] = useState(hitKey(hit));
  useEffect(() => setSelectedKey(hitKey(hit)), [hit]);

  // The frame is cut from the video on demand; when it cannot be (no ffmpeg, no video), the enlarged crop stands in.
  const frameSrc = `/api/reports/${encodeURIComponent(hit.incident.videoId)}/frame?t=${hit.item.timestampSeconds}`;
  const [frameReady, setFrameReady] = useState(false);
  useEffect(() => {
    setFrameReady(false);
    const probe = new Image();
    probe.onload = () => setFrameReady(true);
    probe.src = frameSrc;
    return () => {
      probe.onload = null;
    };
  }, [frameSrc]);

  const inFrame = hitsInFrame(hit, hits);
  const selected = inFrame.find((other) => hitKey(other) === selectedKey) ?? hit;
  const { item } = selected;
  const relationship = relationshipOf(selected, hits);
  const version = versions[selected.incident.videoId];

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        aria-label="Evidence in its frame"
        className="max-h-[92vh] w-full max-w-[calc(100%-2rem)] overflow-auto rounded-3xl bg-white p-5 shadow-panel sm:max-w-5xl"
      >
        <DialogHeader className="flex flex-row items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-moss">
              {selected.incident.incidentType} · {selected.incident.videoId}
            </p>
            <DialogTitle className="text-xl font-semibold">
              {version?.title || selected.incident.title || selected.incident.incidentType}
            </DialogTitle>
          </div>
        </DialogHeader>

        <div className="mt-4 grid gap-5 lg:grid-cols-[1.6fr_1fr]">
          <div className="min-w-0 min-h-0">
            <div className="flex min-w-0 min-h-0 items-center justify-center overflow-hidden rounded-xl bg-black">
              {frameReady ? (
                <FrameViewer
                  boxes={inFrame.map((other) => ({
                    id: hitKey(other),
                    label: other.item.name || other.item.itemId,
                    kind: other.item.itemType,
                    box: other.item.boundingBox,
                  }))}
                  onSelect={setSelectedKey}
                  selectedId={hitKey(selected)}
                  seconds={item.timestampSeconds}
                  src={frameSrc}
                />
              ) : (
                <EvidenceFrame
                  aspect={4 / 3}
                  box={item.boundingBox}
                  kind={item.itemType}
                  label={item.name || item.itemId}
                  seconds={item.timestampSeconds}
                  src={item.cropImageUrl}
                />
              )}
            </div>

            {inFrame.length > 1 && (
              <div className="mt-3">
                <ToggleGroup
                  aria-label="Items in this frame"
                  className="flex flex-wrap justify-start gap-2"
                  onValueChange={(val) => {
                    if (val) setSelectedKey(val);
                  }}
                  type="single"
                  value={hitKey(selected)}
                >
                  {inFrame.map((other) => (
                    <ToggleGroupItem
                      className="h-8 rounded-full border border-ink/15 px-3 text-xs data-[state=on]:bg-ink data-[state=on]:text-white"
                      key={hitKey(other)}
                      value={hitKey(other)}
                      variant="outline"
                    >
                      {other.item.itemId} {other.item.name}
                    </ToggleGroupItem>
                  ))}
                </ToggleGroup>
              </div>
            )}
          </div>

          <div className="space-y-2 text-sm">
            <p className="text-xs text-ink/70">
              <b className="text-ink">{KIND_LABEL[item.itemType]}</b> · <span className="font-mono">{item.itemId}</span> ·{' '}
              {showMatch ? `${matchPercent(selected)}% match · ` : ''}
              {formatClock(item.timestampSeconds)}
              {item.threatLevel != null ? ` · Threat ${item.threatLevel}` : ''}
            </p>
            <h3 className="text-lg font-semibold text-ink">{item.name || item.label}</h3>
            <p className="leading-6 text-ink/70">{item.description}</p>
            <RelationshipLine relationship={relationship} />
            <div className="pt-2">
              <Button asChild className="rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white">
                <Link href={reportHref(selected, version)}>Open report</Link>
              </Button>
              <span className="ml-3 text-xs text-ink-caption">evidence seen at {formatClock(item.timestampSeconds)}</span>
            </div>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
