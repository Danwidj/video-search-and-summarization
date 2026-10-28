// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';

import { EvidenceFrame, KIND_COLOUR, KIND_LABEL } from '@/sections/evidence/components/EvidenceFrame';
import { IncidentThumbnail, SeverityChip } from '@/sections/library/components/Shared';
import { type HitRelationship, type SearchedVersion, matchPercent, reportHref } from '@/lib/library/search';
import type { EvidenceSearchHit } from '@/modules/search/domain/search';
import { formatClock } from '@/modules/reports/domain/normalize';

export function RelationshipLine({ relationship }: { relationship: HitRelationship }) {
  const parts: string[] = [];
  if (relationship.heldBy)
    parts.push(`held by ${relationship.heldBy.itemId}${relationship.heldBy.name ? ` (${relationship.heldBy.name})` : ''}`);
  if (relationship.holds.length) parts.push(`holds ${relationship.holds.map((held) => held.itemId).join(', ')}`);
  return parts.length ? (
    <p className="text-xs text-ink/55" data-testid="hit-relationship">
      {parts.join(' · ')}
    </p>
  ) : null;
}

export function HitCard({
  hit,
  version,
  relationship,
  onView,
  showMatch = true,
}: {
  hit: EvidenceSearchHit;
  version?: SearchedVersion;
  relationship: HitRelationship;
  onView: () => void;
  /** False for a listing with no query, which has no similarity to show. */
  showMatch?: boolean;
}) {
  const { item, incident } = hit;
  return (
    <article className="flex flex-col overflow-hidden rounded-3xl border border-ink/10 bg-white shadow-xs" data-testid="evidence-hit">
      <button
        aria-label={`View ${item.name || item.itemId} in its frame`}
        className="relative block text-left"
        onClick={onView}
        type="button"
      >
        <EvidenceFrame
          aspect={4 / 3}
          box={item.boundingBox}
          className="rounded-none"
          kind={item.itemType}
          label={item.name || item.itemId}
          seconds={item.timestampSeconds}
          src={item.cropImageUrl}
        />
        {showMatch && (
          <span
            className="absolute right-1.5 top-1.5 rounded-full bg-ink px-2 py-0.5 text-[11px] font-bold text-white"
            data-testid="hit-match"
          >
            {matchPercent(hit)}% match
          </span>
        )}
      </button>
      <div className="flex flex-1 flex-col gap-1.5 p-4">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="flex items-center gap-1 font-semibold">
            <i className={`inline-block h-2 w-2 rounded-full ${KIND_COLOUR[item.itemType]}`} />
            {KIND_LABEL[item.itemType]}
          </span>
          <span className="font-mono text-ink/50">{item.itemId}</span>
          {item.threatLevel != null && <span className="text-ink/50">Threat {item.threatLevel}</span>}
          <span className="ml-auto font-mono text-ink/50">{formatClock(item.timestampSeconds)}</span>
        </div>
        <h3 className="text-base font-semibold">{item.name || item.label}</h3>
        <p className="line-clamp-3 text-sm leading-6 text-ink/60">{item.description}</p>
        <RelationshipLine relationship={relationship} />
      </div>
      <Link className="flex items-center gap-3 border-t border-ink/8 bg-canvas/60 p-3 text-xs" href={reportHref(hit, version)}>
        <IncidentThumbnail className="h-10 w-16 shrink-0 rounded-md" url={version?.thumbnailUrl} />
        <span className="min-w-0 flex-1">
          <b className="block truncate">{incident.title || incident.incidentType}</b>
          <span className="block truncate text-ink/50">
            {incident.incidentType} · {incident.videoId}
            {version ? ` · ${version.isOfficial ? 'Official' : 'Latest'} v${version.revisionNo}` : ''}
          </span>
        </span>
        <SeverityChip level={incident.severityLevel} />
      </Link>
    </article>
  );
}
