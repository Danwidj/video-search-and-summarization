// SPDX-License-Identifier: Apache-2.0
'use client';

import { useMemo, useState } from 'react';

import { HitCard } from '@/sections/library/components/HitCard';
import { HitViewer } from '@/sections/library/components/HitViewer';
import { CardSkeleton, ErrorPanel, FilterChip, Select } from '@/sections/library/components/Shared';
import { ITEM_KINDS, type LibrarySearchResponse, filterHits, groupByIncident, hitKey, relationshipOf } from '@/lib/library/search';
import type { EvidenceItemType, EvidenceSearchHit } from '@/modules/search/domain/search';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Pagination, PaginationContent, PaginationItem } from '@/components/ui/pagination';

export interface EvidenceScope {
  incidentId: string;
  title: string;
  filename?: string;
}

type Kind = 'all' | EvidenceItemType;
const KIND_CHIP: Record<Kind, string> = { all: 'All', entity: 'Entities', instrument: 'Instruments', asset: 'Assets' };
const PAGE_SIZE = 12;

export function EvidenceTab({
  query,
  onQuery,
  scope,
  onScope,
  submitted,
  onSubmit,
  result,
  loading,
  error,
  onShowInIncidents,
}: {
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
  onShowInIncidents?: (incident: EvidenceSearchHit['incident']) => void;
}) {
  const [kind, setKind] = useState<Kind>('all');
  const [minThreat, setMinThreat] = useState(1);
  const [incidentType, setIncidentType] = useState('');
  const [grouped, setGrouped] = useState(false);
  const [page, setPage] = useState(1);
  const [viewing, setViewing] = useState<EvidenceSearchHit | null>(null);

  const hits = result?.hits ?? [];
  const incidentTypes = useMemo(() => [...new Set(hits.map((hit) => hit.incident.incidentType).filter(Boolean))].sort(), [hits]);
  const shown = useMemo(
    () =>
      filterHits(hits, { minThreat }).filter(
        (hit) => (kind === 'all' || hit.item.itemType === kind) && (!incidentType || hit.incident.incidentType === incidentType),
      ),
    [hits, minThreat, kind, incidentType],
  );

  const totalPages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE));
  const paginatedHits = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return shown.slice(start, start + PAGE_SIZE);
  }, [shown, page]);

  // A listing of one incident's evidence (no query) has no similarity to show.
  const showMatch = submitted !== '';
  const versions = result?.versions ?? {};
  const card = (hit: EvidenceSearchHit) => (
    <HitCard
      hit={hit}
      key={hitKey(hit)}
      onShowInIncidents={onShowInIncidents}
      onView={() => setViewing(hit)}
      relationship={relationshipOf(hit, hits)}
      showMatch={showMatch}
      version={versions[hit.incident.videoId]}
    />
  );

  return (
    <div>
      <form
        className="flex flex-col gap-3 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          if (query.trim() || scope) {
            setPage(1);
            onSubmit();
          }
        }}
      >
        <div className="relative flex-1">
          <Input
            className="h-10 bg-white"
            maxLength={500}
            onChange={(event) => onQuery(event.target.value)}
            placeholder="Describe what you are looking for, e.g. a man holding a knife"
            type="search"
            value={query}
          />
        </div>
        <Button className="bg-ink font-semibold text-white hover:bg-ink/90" disabled={(!query.trim() && !scope) || loading} type="submit">
          Search
        </Button>
      </form>
      <p className="mt-2 text-xs text-ink/50">
        Searches the official version of each incident, or the latest version when none is official.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Tabs
          onValueChange={(val) => {
            setKind(val as Kind);
            setPage(1);
          }}
          value={kind}
        >
          <TabsList className="border border-ink/10 bg-white">
            {ITEM_KINDS.map((value) => (
              <TabsTrigger className="text-xs" key={value} value={value}>
                {KIND_CHIP[value]}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <div className="w-40">
          <Select
            label="Threat level"
            onChange={(value) => {
              setMinThreat(Number(value));
              setPage(1);
            }}
            options={[
              ['1', 'Any threat'],
              ['2', 'Threat 2+'],
              ['3', 'Threat 3+'],
              ['4', 'Threat 4+'],
              ['5', 'Threat 5'],
            ]}
            value={String(minThreat)}
          />
        </div>

        <div className="w-44">
          <Select
            label="Incident type"
            onChange={(val) => {
              setIncidentType(val);
              setPage(1);
            }}
            options={[['', 'All incident types'], ...incidentTypes.map((value): [string, string] => [value, value])]}
            value={incidentType}
          />
        </div>

        <div className="ml-auto flex items-center gap-2">
          <Checkbox checked={grouped} id="group-by-incident" onCheckedChange={(checked) => setGrouped(checked === true)} />
          <Label className="cursor-pointer text-sm font-normal text-ink/80" htmlFor="group-by-incident">
            Group by incident
          </Label>
        </div>
      </div>

      {scope && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink/55">
          Searching only{' '}
          <FilterChip label={scope.filename ? `${scope.title} · ${scope.filename}` : scope.title} onRemove={() => onScope(null)} />
        </div>
      )}

      {loading ? (
        <CardSkeleton count={6} label="Searching evidence" />
      ) : error ? (
        <ErrorPanel message={error} onRetry={onSubmit} />
      ) : !result ? (
        <div className="mt-8 rounded-2xl border border-dashed border-ink/20 p-14 text-center">
          <h2 className="text-xl font-semibold text-ink">Search the evidence in every incident</h2>
          <p className="mt-2 text-sm text-ink/50">Describe a person, object or place. Every ranked match is shown with its video time.</p>
        </div>
      ) : shown.length === 0 ? (
        <div className="mt-8 rounded-2xl border border-dashed border-ink/20 p-14 text-center">
          <h2 className="text-xl font-semibold text-ink">No evidence found.</h2>
          <p className="mt-2 text-sm text-ink/50">Try fewer words or a different kind filter.</p>
        </div>
      ) : (
        <>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <p className="text-sm text-ink/50" data-testid="hit-count">
              {showMatch ? (
                <>
                  {shown.length} {shown.length === 1 ? 'match' : 'matches'} for &ldquo;{submitted}&rdquo;
                </>
              ) : (
                <>
                  {shown.length} evidence {shown.length === 1 ? 'item' : 'items'}, in video order
                </>
              )}
            </p>
          </div>

          {grouped ? (
            <div className="mt-4 space-y-8">
              {groupByIncident(shown).map((group) => (
                <section key={group.videoId}>
                  <h2 className="text-lg font-semibold">
                    {group.incident.title || group.incident.incidentType}{' '}
                    <span className="font-mono text-xs font-normal text-ink-caption">{group.videoId}</span>
                  </h2>
                  <div className="mt-3 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{group.hits.map(card)}</div>
                </section>
              ))}
            </div>
          ) : (
            <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3">{paginatedHits.map(card)}</div>
          )}

          {!grouped && shown.length > PAGE_SIZE && (
            <nav aria-label="Evidence pages" className="mt-8 flex flex-col items-center gap-3">
              <p className="text-xs text-ink/55">
                Showing {(page - 1) * PAGE_SIZE + 1}-{Math.min(page * PAGE_SIZE, shown.length)} of {shown.length} items
              </p>
              <Pagination>
                <PaginationContent>
                  <PaginationItem>
                    <Button disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))} size="sm" variant="outline">
                      Previous
                    </Button>
                  </PaginationItem>
                  {Array.from({ length: totalPages }, (_, i) => i + 1).map((p) => (
                    <PaginationItem key={p}>
                      <Button
                        className={p === page ? 'bg-ink text-white' : ''}
                        onClick={() => setPage(p)}
                        size="sm"
                        variant={p === page ? 'default' : 'outline'}
                      >
                        {p}
                      </Button>
                    </PaginationItem>
                  ))}
                  <PaginationItem>
                    <Button
                      disabled={page >= totalPages}
                      onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                      size="sm"
                      variant="outline"
                    >
                      Next
                    </Button>
                  </PaginationItem>
                </PaginationContent>
              </Pagination>
            </nav>
          )}
        </>
      )}

      {viewing && <HitViewer hit={viewing} hits={hits} onClose={() => setViewing(null)} showMatch={showMatch} versions={versions} />}
    </div>
  );
}
