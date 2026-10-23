// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { EvidenceFrame, KIND_LABEL } from '@/components/evidence-frame';
import { FrameViewer } from '@/components/frame-viewer';
import { RelationshipLine } from '@/components/library/hit-card';
import { type SearchedVersion, hitKey, hitsInFrame, matchPercent, relationshipOf, reportHref } from '@/lib/library/search';
import type { EvidenceSearchHit } from '@/lib/ports/search';
import { formatClock } from '@/modules/reports/domain/normalize';

/** The modal opened from any crop: the item's frame with every box found at that moment, its details and a way into the report at that time. */
export function HitViewer({ hit, hits, versions, onClose }: { hit: EvidenceSearchHit; hits: EvidenceSearchHit[]; versions: Record<string, SearchedVersion>; onClose: () => void }) {
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
    return () => { probe.onload = null; };
  }, [frameSrc]);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const inFrame = hitsInFrame(hit, hits);
  const selected = inFrame.find((other) => hitKey(other) === selectedKey) ?? hit;
  const { item } = selected;
  const relationship = relationshipOf(selected, hits);
  const version = versions[selected.incident.videoId];
  return (
    <div aria-label="Evidence in its frame" aria-modal="true" className="fixed inset-0 z-50 grid place-items-center bg-ink/60 p-4" onClick={onClose} role="dialog">
      <div className="max-h-[92vh] w-full max-w-5xl overflow-auto rounded-[1.5rem] bg-white p-5 shadow-panel" onClick={(event) => event.stopPropagation()}>
        <div className="flex items-start justify-between gap-4">
          <div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-moss">{selected.incident.incidentType} · {selected.incident.videoId}</p><h2 className="text-xl font-semibold">{selected.incident.title || selected.incident.incidentType}</h2></div>
          <button aria-label="Close viewer" className="action" onClick={onClose} type="button">Close</button>
        </div>
        <div className="mt-4 grid gap-5 lg:grid-cols-[1.6fr_1fr]">
          <div>
            {frameReady
              ? <FrameViewer boxes={inFrame.map((other) => ({ id: hitKey(other), label: other.item.name || other.item.itemId, kind: other.item.itemType, box: other.item.boundingBox }))} onSelect={setSelectedKey} selectedId={hitKey(selected)} seconds={item.timestampSeconds} src={frameSrc} />
              : <EvidenceFrame aspect={4 / 3} box={item.boundingBox} kind={item.itemType} label={item.name || item.itemId} seconds={item.timestampSeconds} src={item.cropImageUrl} />}
            {inFrame.length > 1 && <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Items in this frame">{inFrame.map((other) => <button aria-pressed={hitKey(other) === hitKey(selected)} className={`action ${hitKey(other) === hitKey(selected) ? 'bg-ink text-white' : ''}`} key={hitKey(other)} onClick={() => setSelectedKey(hitKey(other))} type="button">{other.item.itemId} {other.item.name}</button>)}</div>}
          </div>
          <div className="space-y-2 text-sm">
            <p className="text-xs"><b>{KIND_LABEL[item.itemType]}</b> · <span className="font-mono">{item.itemId}</span> · {matchPercent(selected)}% match · {formatClock(item.timestampSeconds)}{item.threatLevel != null ? ` · Threat ${item.threatLevel}` : ''}</p>
            <h3 className="text-lg font-semibold">{item.name || item.label}</h3>
            <p className="leading-6 text-ink/70">{item.description}</p>
            <RelationshipLine relationship={relationship} />
            {selected.critic.verdict !== 'unverified' && <p className="text-xs text-ink/55">Critic: {selected.critic.verdict}{selected.critic.rationale ? ` - ${selected.critic.rationale}` : ''}</p>}
            <Link className="mt-2 inline-block rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white" href={reportHref(selected, version)}>Open report</Link>
            <span className="ml-3 text-xs text-ink/50">evidence seen at {formatClock(item.timestampSeconds)}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
