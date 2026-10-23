// SPDX-License-Identifier: Apache-2.0
'use client';

import { useMemo, useState } from 'react';

import { HitCard } from '@/components/library/hit-card';
import { HitViewer } from '@/components/library/hit-viewer';
import { CardSkeleton, ErrorPanel, FilterChip, Select } from '@/components/library/shared';
import { ITEM_KINDS, type LibrarySearchResponse, filterHits, groupByIncident, hitKey, relationshipOf, withoutRejected } from '@/lib/library/search';
import type { EvidenceItemType, EvidenceSearchHit } from '@/lib/ports/search';

export interface EvidenceScope { videoId: string; title: string }

type Kind = 'all' | EvidenceItemType;
const KIND_CHIP: Record<Kind, string> = { all: 'All', entity: 'Entities', instrument: 'Instruments', asset: 'Assets' };

export function EvidenceTab({ query, onQuery, scope, onScope, submitted, onSubmit, result, loading, error }: {
  query: string;
  onQuery: (value: string) => void;
  scope: EvidenceScope | null;
  onScope: (scope: EvidenceScope | null) => void;
  /** The text the shown result was searched for. */
  submitted: string;
  onSubmit: () => void;
  result: LibrarySearchResponse | null;
  loading: boolean;
  error: string;
}) {
  const [kind, setKind] = useState<Kind>('all');
  const [minThreat, setMinThreat] = useState(1);
  const [incidentType, setIncidentType] = useState('');
  const [grouped, setGrouped] = useState(false);
  const [viewing, setViewing] = useState<EvidenceSearchHit | null>(null);
  const [showRejected, setShowRejected] = useState(false);

  const hits = result?.hits ?? [];
  const incidentTypes = useMemo(() => [...new Set(hits.map((hit) => hit.incident.incidentType).filter(Boolean))].sort(), [hits]);
  const visible = useMemo(
    () => filterHits(hits, { minThreat, videoId: scope?.videoId ?? null }).filter((hit) => (kind === 'all' || hit.item.itemType === kind) && (!incidentType || hit.incident.incidentType === incidentType)),
    [hits, minThreat, scope, kind, incidentType],
  );
  const rejected = visible.length - withoutRejected(visible, false).length;
  const shown = useMemo(() => withoutRejected(visible, showRejected), [visible, showRejected]);
  const versions = result?.versions ?? {};
  const card = (hit: EvidenceSearchHit) => <HitCard hit={hit} key={hitKey(hit)} onView={() => setViewing(hit)} relationship={relationshipOf(hit, hits)} version={versions[hit.incident.videoId]} />;

  return (
    <div>
      <form className="flex flex-col gap-3 sm:flex-row" onSubmit={(event) => { event.preventDefault(); if (query.trim()) onSubmit(); }}>
        <label className="flex-1"><span className="sr-only">Find evidence</span><input className="control" maxLength={500} onChange={(event) => onQuery(event.target.value)} placeholder="Describe what you are looking for, e.g. a man holding a knife" type="search" value={query} /></label>
        <button className="rounded-full bg-ink px-6 py-3 text-sm font-semibold text-white disabled:opacity-40" disabled={!query.trim() || loading} type="submit">Search</button>
      </form>
      <p className="mt-2 text-xs text-ink/50">Searches the official version of each incident, or the latest version when none is official.</p>
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <div className="flex gap-1.5" role="group" aria-label="Evidence kind">{ITEM_KINDS.map((value) => <button aria-pressed={kind === value} className={`action ${kind === value ? 'bg-ink text-white' : 'bg-white'}`} key={value} onClick={() => setKind(value)} type="button">{KIND_CHIP[value]}</button>)}</div>
        <div className="w-40"><Select label="Threat level" onChange={(value) => setMinThreat(Number(value))} options={[['1', 'Any threat'], ['2', 'Threat 2+'], ['3', 'Threat 3+'], ['4', 'Threat 4+'], ['5', 'Threat 5']]} value={String(minThreat)} /></div>
        <div className="w-44"><Select label="Incident type" onChange={setIncidentType} options={[['', 'All incident types'], ...incidentTypes.map((value): [string, string] => [value, value])]} value={incidentType} /></div>
        <label className="ml-auto flex items-center gap-2 text-sm"><input checked={grouped} onChange={(event) => setGrouped(event.target.checked)} type="checkbox" />Group by incident</label>
      </div>
      {scope && <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink/55">Searching only <FilterChip label={scope.title} onRemove={() => onScope(null)} /></div>}

      {loading ? <CardSkeleton count={6} label="Searching evidence" />
        : error ? <ErrorPanel message={error} onRetry={onSubmit} />
        : !result ? <div className="mt-8 rounded-2xl border border-dashed border-ink/20 p-14 text-center"><h2 className="text-xl font-semibold">Search the evidence in every incident</h2><p className="mt-2 text-sm text-ink/50">Describe a person, object or place. Every ranked match is shown with its video time.</p></div>
        : shown.length === 0 ? <div className="mt-8 rounded-2xl border border-dashed border-ink/20 p-14 text-center"><h2 className="text-xl font-semibold">No evidence found.</h2><p className="mt-2 text-sm text-ink/50">Try fewer words or a different kind filter.</p>{rejected > 0 && <button aria-pressed={showRejected} className="action mt-4" onClick={() => setShowRejected(true)} type="button">Show {rejected} rejected</button>}</div>
        : <>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-ink/50" data-testid="hit-count">{shown.length} {shown.length === 1 ? 'match' : 'matches'} for &ldquo;{submitted}&rdquo;</p>
            {rejected > 0 && <button aria-pressed={showRejected} className="action" data-testid="rejected-toggle" onClick={() => setShowRejected((value) => !value)} type="button">{showRejected ? `Hide ${rejected} rejected` : `Show ${rejected} rejected`}</button>}
          </div>
          {grouped
            ? <div className="mt-4 space-y-8">{groupByIncident(shown).map((group) => <section key={group.videoId}><h2 className="text-lg font-semibold">{group.incident.title || group.incident.incidentType} <span className="font-mono text-xs font-normal text-ink/45">{group.videoId}</span></h2><div className="mt-3 grid gap-5 md:grid-cols-2 xl:grid-cols-3">{group.hits.map(card)}</div></section>)}</div>
            : <div className="mt-4 grid gap-5 md:grid-cols-2 xl:grid-cols-3">{shown.map(card)}</div>}
        </>}
      {viewing && <HitViewer hit={viewing} hits={hits} onClose={() => setViewing(null)} versions={versions} />}
    </div>
  );
}

