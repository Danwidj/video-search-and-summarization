// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

import { EvidenceTab, type EvidenceScope } from '@/sections/library/components/EvidenceTab';
import { IncidentCard } from '@/sections/library/components/IncidentCard';
import { CardSkeleton, ErrorPanel, FilterChip, Select } from '@/sections/library/components/Shared';
import {
  type DatePreset,
  EMPTY_FILTERS,
  FILTER_KEYS,
  type IncidentFilters,
  activeFilters,
  filterParams,
  parseFilters,
  presetAfter,
} from '@/lib/library/filters';
import type { LibrarySearchResponse } from '@/lib/library/search';
import type { ReportLibraryItem } from '@/modules/reports/domain/storage';
import { getViewerTimeZone } from '@/lib/time';

type Tab = 'incidents' | 'evidence';
const STATE_KEY = 'report-library-state';
const PAGE_SIZE = 6;

export function Library() {
  const query = useSearchParams();
  const router = useRouter();
  const [tab, setTab] = useState<Tab>(query.get('tab') === 'evidence' ? 'evidence' : 'incidents');
  const [filters, setFilters] = useState<IncidentFilters>(EMPTY_FILTERS);
  const [searchText, setSearchText] = useState('');
  const [ready, setReady] = useState(false);
  const [timeZone, setTimeZone] = useState('UTC');
  const [reports, setReports] = useState<ReportLibraryItem[]>([]);
  const [incidentTypes, setIncidentTypes] = useState<string[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [searchMode, setSearchMode] = useState<'semantic' | 'text' | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [library, setLibrary] = useState<'unknown' | 'empty' | 'has-reports'>('unknown');
  const loadSequence = useRef(0);
  const restoredPosition = useRef(false);

  const [evidenceQuery, setEvidenceQuery] = useState('');
  const [submitted, setSubmitted] = useState('');
  const [scope, setScope] = useState<EvidenceScope | null>(null);
  const [result, setResult] = useState<LibrarySearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState('');
  const searchSequence = useRef(0);

  function apply(next: Partial<IncidentFilters>, keepPage = false) {
    setFilters((current) => ({ ...current, ...next, page: keepPage ? (next.page ?? current.page) : 1 }));
  }

  // The URL is the filter state: any filter in it (dashboard links, shared links,
  // refresh, back/forward) is applied alone; the remembered state only serves a bare /library.
  // biome-ignore lint/correctness/useExhaustiveDependencies: initialisation on mount from query URL and storage
  useEffect(() => {
    setTimeZone(getViewerTimeZone());
    let initial = EMPTY_FILTERS;
    if (FILTER_KEYS.some((key) => query.has(key))) initial = parseFilters(query);
    else {
      try {
        const state = JSON.parse(window.sessionStorage.getItem(STATE_KEY) || 'null') as { filters?: IncidentFilters } | null;
        if (state?.filters) initial = { ...EMPTY_FILTERS, ...state.filters };
      } catch {
        /* ignore stale state */
      }
    }
    setFilters(initial);
    setSearchText(initial.search);
    setReady(true);
  }, []);

  async function load(signal?: AbortSignal) {
    const sequence = ++loadSequence.current;
    setLoading(true);
    setError('');
    try {
      const params = filterParams(filters);
      const response = await fetch(
        `/api/reports?${new URLSearchParams([...params, ['page', String(filters.page)], ['sort', filters.sort], ['timezone', timeZone]])}`,
        { cache: 'no-store', signal },
      );
      const payload = (await response.json()) as {
        reports?: ReportLibraryItem[];
        incidentTypes?: string[];
        pagination?: { totalItems: number; totalPages: number };
        searchMode?: 'semantic' | 'text' | null;
        error?: string;
      };
      if (!response.ok || !payload.reports) throw new Error(payload.error || 'Could not load incidents');
      if (sequence !== loadSequence.current) return;
      setReports(payload.reports);
      setIncidentTypes(payload.incidentTypes || []);
      setTotalItems(payload.pagination?.totalItems || 0);
      setTotalPages(payload.pagination?.totalPages || 0);
      setSearchMode(payload.searchMode ?? null);
      if (activeFilters(filters).length === 0) setLibrary(payload.reports.length ? 'has-reports' : 'empty');
      else setLibrary((current) => (payload.reports?.length ? 'has-reports' : current));
      router.replace(`/library?${new URLSearchParams([...(tab === 'evidence' ? [['tab', 'evidence']] : []), ...params])}`, {
        scroll: false,
      });
    } catch (cause) {
      if (!(cause instanceof DOMException && cause.name === 'AbortError') && sequence === loadSequence.current)
        setError(cause instanceof Error ? cause.message : 'Could not load incidents');
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }

  // biome-ignore lint/correctness/useExhaustiveDependencies: load is triggered by filters and timeZone changes
  useEffect(() => {
    if (!ready || tab !== 'incidents') return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [ready, tab, filters, timeZone]);

  useEffect(() => {
    if (loading || restoredPosition.current) return;
    restoredPosition.current = true;
    try {
      const state = JSON.parse(window.sessionStorage.getItem(STATE_KEY) || '{}') as { scrollY?: number; revisionId?: string };
      window.requestAnimationFrame(() => {
        if (state.revisionId) document.getElementById(`report-${state.revisionId}`)?.focus({ preventScroll: true });
        window.scrollTo({ top: state.scrollY || 0 });
      });
    } catch {
      /* ignore stale state */
    }
  }, [loading]);

  function rememberPosition(item: ReportLibraryItem) {
    window.sessionStorage.setItem(STATE_KEY, JSON.stringify({ filters, scrollY: window.scrollY, revisionId: String(item.revisionId) }));
  }

  async function deleteReport(item: ReportLibraryItem) {
    if (!window.confirm('Permanently delete this video and every version of its report? Versions are never deleted one by one.')) return;
    setBusy(item.videoId);
    try {
      const response = await fetch(`/api/reports/${encodeURIComponent(item.videoId)}/delete`, { method: 'DELETE' });
      const payload = (await response.json()) as { error?: string };
      if (!response.ok) throw new Error(payload.error || 'Delete failed');
      if (reports.length === 1 && filters.page > 1) apply({ page: filters.page - 1 }, true);
      else await load();
    } catch (cause) {
      window.alert(cause instanceof Error ? cause.message : 'Delete failed');
    } finally {
      setBusy('');
    }
  }

  async function searchEvidence(text: string) {
    const trimmed = text.trim();
    if (!trimmed) return;
    const sequence = ++searchSequence.current;
    setSearching(true);
    setSearchError('');
    setSubmitted(trimmed);
    try {
      const response = await fetch('/api/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: trimmed }),
      });
      const payload = (await response.json()) as LibrarySearchResponse & { error?: string };
      if (!response.ok || !Array.isArray(payload.hits)) throw new Error(payload.error || 'Evidence search failed');
      if (sequence === searchSequence.current) setResult(payload);
    } catch (cause) {
      if (sequence === searchSequence.current) setSearchError(cause instanceof Error ? cause.message : 'Evidence search failed');
    } finally {
      if (sequence === searchSequence.current) setSearching(false);
    }
  }

  function chooseTab(next: Tab) {
    setTab(next);
    // The incident scope is temporary: it lasts only while the person stays in the evidence tab.
    if (next === 'incidents') setScope(null);
  }

  function searchEvidenceIn(item: ReportLibraryItem) {
    setScope({ videoId: item.videoId, title: item.title || item.incident_type });
    setTab('evidence');
  }

  const chips = activeFilters(filters);
  const datePreset: DatePreset | 'custom' =
    !filters.after && !filters.before
      ? 'any'
      : ((['today', '7d', '30d'] as DatePreset[]).find((preset) => !filters.before && presetAfter(preset) === filters.after) ?? 'custom');
  const first = (filters.page - 1) * PAGE_SIZE + 1;

  return (
    <div className="mx-auto max-w-[1500px] px-6 pb-20 pt-8 lg:px-12">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <h1 className="text-3xl font-semibold tracking-[-0.04em] sm:text-4xl">Incident reports</h1>
        <Link className="w-fit rounded-full bg-ink px-5 py-3 text-sm font-semibold text-white" href="/">
          + Analyze video
        </Link>
      </div>

      <div className="mt-6 flex gap-1 border-b border-ink/10" role="tablist">
        {(
          [
            ['incidents', 'Find incidents'],
            ['evidence', 'Find evidence'],
          ] as [Tab, string][]
        ).map(([value, label]) => (
          <button
            aria-selected={tab === value}
            className={`-mb-px border-b-2 px-4 py-2.5 text-sm font-semibold ${tab === value ? 'border-ink text-ink' : 'border-transparent text-ink/50 hover:text-ink'}`}
            key={value}
            onClick={() => chooseTab(value)}
            role="tab"
            type="button"
          >
            {label}
          </button>
        ))}
      </div>

      <section className="mt-5">
        {tab === 'evidence' ? (
          <EvidenceTab
            error={searchError}
            loading={searching}
            onQuery={setEvidenceQuery}
            onScope={setScope}
            onSubmit={() => void searchEvidence(evidenceQuery)}
            query={evidenceQuery}
            result={result}
            scope={scope}
            submitted={submitted}
          />
        ) : (
          <>
            <form
              className="flex flex-col gap-3 sm:flex-row"
              onSubmit={(event) => {
                event.preventDefault();
                apply({ search: searchText });
              }}
            >
              <label className="flex-1">
                <span className="sr-only">Search incidents</span>
                <input
                  className="control"
                  onChange={(event) => setSearchText(event.target.value)}
                  placeholder="Search incident titles, summaries and evidence"
                  type="search"
                  value={searchText}
                />
              </label>
              <button className="rounded-full bg-ink px-6 py-3 text-sm font-semibold text-white" type="submit">
                Search
              </button>
            </form>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
              <Select
                label="Sort incidents"
                onChange={(value) => apply({ sort: value === 'oldest' ? 'oldest' : 'newest' })}
                options={[
                  ['newest', 'Newest first'],
                  ['oldest', 'Oldest first'],
                ]}
                value={filters.sort}
              />
              <Select
                label="Incident type"
                onChange={(value) => apply({ type: value })}
                options={[['', 'All incident types'], ...incidentTypes.map((value): [string, string] => [value, value])]}
                value={filters.type}
              />
              <Select
                label="Status"
                onChange={(value) => apply({ official: value === 'official' })}
                options={[
                  ['', 'Any status'],
                  ['official', 'Has an official version'],
                ]}
                value={filters.official ? 'official' : ''}
              />
              <Select
                label="Severity"
                onChange={(value) => apply({ severity: value })}
                options={[
                  ['', 'Any severity'],
                  ['low', 'Low (1-2)'],
                  ['medium', 'Medium (3)'],
                  ['high', 'High (4-5)'],
                ]}
                value={filters.severity}
              />
              <Select
                label="Added"
                onChange={(value) => apply({ after: presetAfter(value as DatePreset), before: '' })}
                options={[
                  ['any', 'Any date'],
                  ['today', 'Today'],
                  ['7d', 'Last 7 days'],
                  ['30d', 'Last 30 days'],
                  ...(datePreset === 'custom' ? [['custom', 'Custom range'] as [string, string]] : []),
                ]}
                value={datePreset}
              />
            </div>
            {chips.length > 0 && (
              <div className="mt-3 flex flex-wrap items-center gap-2" data-testid="active-filters">
                {chips.map((chip) => (
                  <FilterChip
                    key={chip.key}
                    label={chip.label}
                    onRemove={() => {
                      apply(chip.clear);
                      if (chip.key === 'search') setSearchText('');
                    }}
                  />
                ))}
                <button
                  className="text-xs font-semibold text-moss"
                  onClick={() => {
                    setFilters(EMPTY_FILTERS);
                    setSearchText('');
                  }}
                  type="button"
                >
                  Clear all
                </button>
              </div>
            )}
            {filters.entity || filters.instrument || filters.asset ? (
              <p className="mt-2 text-xs text-ink/50">
                {filters.exact ? 'Instrument and asset names are matched exactly.' : 'Instrument and asset names match partial text.'}
              </p>
            ) : null}
            {filters.fromTime || filters.toTime ? <p className="mt-1 text-xs text-ink/50">Times are in {timeZone}.</p> : null}

            <div className="mt-5 text-sm text-ink/50">
              {totalItems} {totalItems === 1 ? 'incident' : 'incidents'}
            </div>
            {searchMode === 'text' && (
              <p className="mt-1 text-xs text-ink/50" data-testid="search-mode">
                Matched on incident text: meaning search is unavailable or found nothing.
              </p>
            )}
            {loading ? (
              <CardSkeleton label="Loading incidents" />
            ) : error ? (
              <ErrorPanel message={error} onRetry={() => void load()} />
            ) : reports.length === 0 ? (
              library === 'empty' ? (
                <div className="mt-8 rounded-2xl border border-dashed border-ink/20 p-14 text-center">
                  <h2 className="text-xl font-semibold">Your library is empty.</h2>
                  <p className="mt-2 text-sm text-ink/50">Analyze a video to create the first incident report.</p>
                  <Link className="mt-4 inline-block rounded-full bg-ink px-5 py-3 text-sm font-semibold text-white" href="/">
                    + Analyze video
                  </Link>
                </div>
              ) : (
                <div className="mt-8 rounded-2xl border border-dashed border-ink/20 p-14 text-center">
                  <h2 className="text-xl font-semibold">No incidents match.</h2>
                  <p className="mt-2 text-sm text-ink/50">Clear the filters or search the evidence instead.</p>
                  <div className="mt-4 flex justify-center gap-3">
                    {chips.length > 0 && (
                      <button
                        className="action"
                        onClick={() => {
                          setFilters(EMPTY_FILTERS);
                          setSearchText('');
                        }}
                        type="button"
                      >
                        Clear all
                      </button>
                    )}
                    {filters.search.trim() && (
                      <button
                        className="action"
                        onClick={() => {
                          setEvidenceQuery(filters.search.trim());
                          setTab('evidence');
                          void searchEvidence(filters.search);
                        }}
                        type="button"
                      >
                        Search evidence for &ldquo;{filters.search.trim()}&rdquo;
                      </button>
                    )}
                  </div>
                </div>
              )
            ) : (
              <>
                <div className="mt-4 grid gap-5 md:grid-cols-2 xl:grid-cols-3">
                  {reports.map((item) => (
                    <IncidentCard
                      busy={busy === item.videoId}
                      item={item}
                      key={item.videoId}
                      onDelete={deleteReport}
                      onOpen={rememberPosition}
                      onSearchEvidence={searchEvidenceIn}
                    />
                  ))}
                </div>
                <nav aria-label="Incident pages" className="mt-8 flex flex-col items-center gap-3">
                  <p className="text-sm font-semibold text-ink/65">
                    Showing {first}-{Math.min(filters.page * PAGE_SIZE, totalItems)} of {totalItems} incidents
                  </p>
                  <div className="flex flex-wrap items-center justify-center gap-2">
                    <button
                      className="action"
                      disabled={filters.page <= 1}
                      onClick={() => apply({ page: filters.page - 1 }, true)}
                      type="button"
                    >
                      Previous
                    </button>
                    {Array.from({ length: totalPages }, (_, index) => index + 1).map((value) => (
                      <button
                        aria-current={value === filters.page ? 'page' : undefined}
                        aria-label={`Page ${value}`}
                        className={`grid h-9 min-w-9 place-items-center rounded-full text-sm font-semibold ${value === filters.page ? 'bg-ink text-white' : 'border border-ink/10 bg-white'}`}
                        key={value}
                        onClick={() => apply({ page: value }, true)}
                        type="button"
                      >
                        {value}
                      </button>
                    ))}
                    <button
                      className="action"
                      disabled={filters.page >= totalPages}
                      onClick={() => apply({ page: filters.page + 1 }, true)}
                      type="button"
                    >
                      Next
                    </button>
                  </div>
                </nav>
              </>
            )}
          </>
        )}
      </section>
    </div>
  );
}
