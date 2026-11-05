// SPDX-License-Identifier: Apache-2.0
'use client';

import { MIN_SIMILARITY } from '@/lib/search/min-similarity';
import { useEffect, useMemo, useState } from 'react';

import { HitCard } from '@/sections/library/components/HitCard';
import { CardSkeleton, ErrorPanel, FilterChip, Select } from '@/sections/library/components/Shared';
import {
  ITEM_KINDS,
  type EvidenceSort,
  type LibrarySearchResponse,
  SORT_LABEL,
  groupByIncident,
  hitKey,
  sortHits,
  videoName,
} from '@/lib/library/search';
import type { EvidenceItemType, EvidenceSearchHit } from '@/modules/search/domain/search';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Pagination, PaginationContent, PaginationItem } from '@/components/ui/pagination';

export interface EvidenceScope {
  videoId: string;
  title: string;
  filename?: string;
}

type Kind = 'all' | EvidenceItemType;
const KIND_CHIP: Record<Kind, string> = { all: 'All', entity: 'Entities', instrument: 'Instruments', asset: 'Assets' };
const PAGE_SIZE = 12;
const EXAMPLE_SEARCHES = ['black bear', 'man in white shirt', 'man holding a handgun'];

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
}: {
  query: string;
  onQuery: (value: string) => void;
  scope: EvidenceScope | null;
  onScope: (scope: EvidenceScope | null) => void;
  /** The text the shown result was searched for. */
  submitted: string;
  /** Runs the search; with text, that text is searched (an example), otherwise the query box. */
  onSubmit: (text?: string) => void;
  result: LibrarySearchResponse | null;
  loading: boolean;
  error: string;
}) {
  const [kind, setKind] = useState<Kind>('all');
  const [incidentType, setIncidentType] = useState('');
  const [videoId, setVideoId] = useState('');
  const [sort, setSort] = useState<EvidenceSort>('match');
  const [grouped, setGrouped] = useState(false);
  const [page, setPage] = useState(1);

  const hits = result?.hits ?? [];
  const versions = result?.versions ?? {};
  // A new result starts with every filter off and the default order; they work on the returned hits only.
  // biome-ignore lint/correctness/useExhaustiveDependencies: result is the trigger
  useEffect(() => {
    setKind('all');
    setIncidentType('');
    setVideoId('');
    setSort('match');
    setPage(1);
  }, [result]);
  const incidentTypes = useMemo(() => [...new Set(hits.map((hit) => hit.incident.incidentType).filter(Boolean))].sort(), [hits]);
  const videos = useMemo(() => {
    const byId = new Map<string, string>();
    for (const hit of hits) if (!byId.has(hit.incident.videoId)) byId.set(hit.incident.videoId, videoName(hit, versions));
    return [...byId.entries()].sort((a, b) => a[1].localeCompare(b[1]));
  }, [hits, versions]);
  const shown = useMemo(
    () =>
      sortHits(
        hits.filter(
          (hit) =>
            (kind === 'all' || hit.item.itemType === kind) &&
            (!incidentType || hit.incident.incidentType === incidentType) &&
            (!videoId || hit.incident.videoId === videoId),
        ),
        sort,
        versions,
      ),
    [hits, kind, incidentType, videoId, sort, versions],
  );

  const totalPages = Math.max(1, Math.ceil(shown.length / PAGE_SIZE));
  const paginatedHits = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE;
    return shown.slice(start, start + PAGE_SIZE);
  }, [shown, page]);

  // A listing of one incident's evidence (no query) has no similarity to show, and its default order is video time.
  const showMatch = submitted !== '';
  const sortOptions = (['match', 'date', 'threat', 'severity'] as EvidenceSort[]).map((value): [string, string] => [
    value,
    value === 'match' && !showMatch ? 'Video order' : SORT_LABEL[value],
  ]);
  const card = (hit: EvidenceSearchHit) => (
    <HitCard hit={hit} key={hitKey(hit)} showMatch={showMatch} version={versions[hit.incident.videoId]} />
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
        One version per incident: the official version, otherwise the latest. Evidence matches of {Math.round(MIN_SIMILARITY * 100)}% or
        better are shown.
      </p>

      {result && (
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

          <div className="w-52">
            <Select
              label="Video"
              onChange={(val) => {
                setVideoId(val);
                setPage(1);
              }}
              options={[['', 'All videos'], ...videos]}
              value={videoId}
            />
          </div>

          <div className="w-48">
            <Select
              label="Sort"
              onChange={(val) => {
                setSort(val as EvidenceSort);
                setPage(1);
              }}
              options={sortOptions.map(([value, label]): [string, string] => [value, `Sort: ${label}`])}
              value={sort}
            />
          </div>

          <div className="ml-auto flex items-center gap-2">
            <Checkbox checked={grouped} id="group-by-incident" onCheckedChange={(checked) => setGrouped(checked === true)} />
            <Label className="cursor-pointer text-sm font-normal text-ink/80" htmlFor="group-by-incident">
              Group by incident
            </Label>
          </div>
        </div>
      )}

      {scope && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-ink/55">
          Searching only{' '}
          <FilterChip label={scope.filename ? `${scope.title} · ${scope.filename}` : scope.title} onRemove={() => onScope(null)} />
        </div>
      )}

      {loading ? (
        <CardSkeleton count={6} label="Searching evidence" />
      ) : error ? (
        <ErrorPanel message={error} onRetry={() => onSubmit()} />
      ) : !result ? (
        <div className="mt-8 rounded-2xl border border-dashed border-ink/20 px-14 pb-10 pt-12 text-center" data-testid="evidence-welcome">
          <h2 className="text-2xl font-semibold text-ink">Find evidence across every incident</h2>
          <p className="mx-auto mt-2.5 max-w-[560px] text-[15px] text-ink/50">
            Describe a person, object or place, and see the moments in your videos that match it, ranked best first.
          </p>
          <p className="mt-5 text-xs font-bold uppercase tracking-[0.06em] text-moss">Try a search:</p>
          <div className="mt-2.5 flex flex-wrap justify-center gap-2.5">
            {EXAMPLE_SEARCHES.map((example) => (
              <button
                className="rounded-full border border-ink/10 bg-white px-4 py-2 text-sm text-ink hover:border-moss hover:bg-[#f7f8f4]"
                data-testid="evidence-example"
                key={example}
                onClick={() => {
                  onQuery(example);
                  setPage(1);
                  onSubmit(example);
                }}
                type="button"
              >
                {example}
              </button>
            ))}
          </div>
          <p className="mt-5 text-[12.5px] text-ink/50">
            Type your own words above and press Search. Only matches of {Math.round(MIN_SIMILARITY * 100)}% or better are shown.
          </p>
        </div>
      ) : shown.length === 0 ? (
        <div className="mt-8 rounded-2xl border border-dashed border-ink/20 p-14 text-center">
          <h2 className="text-xl font-semibold text-ink">No evidence found.</h2>
          <p className="mt-2 text-sm text-ink/50">
            {showMatch ? `Only matches of ${Math.round(MIN_SIMILARITY * 100)}% or better are shown. ` : ''}Try fewer words or a different
            kind filter.
          </p>
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
    </div>
  );
}
