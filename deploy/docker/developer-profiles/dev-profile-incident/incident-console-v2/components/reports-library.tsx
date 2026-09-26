// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

import type { AnalysisReport } from '@/lib/analysis/schema';
import type { ReportLibraryItem, ReviewStatus } from '@/lib/reports/storage';
import { reportThumbnailView } from '@/lib/reports/thumbnail';

type Sort = 'newest' | 'oldest' | 'severity-high' | 'severity-low' | 'confidence-high' | 'confidence-low';
type DatePreset = 'all' | 'today' | '7d' | '30d' | 'custom';

function severityClass(level: number) {
  if (level >= 4) return 'bg-[#ffe8df] text-[#9b3518]';
  if (level === 3) return 'bg-[#fff1c7] text-[#765300]';
  return 'bg-signal/15 text-moss';
}

function statusLabel(status: ReviewStatus) {
  return status === 'under review' ? 'Under review' : status[0].toUpperCase() + status.slice(1);
}

export function ReportsLibrary() {
  const query = useSearchParams();
  const router = useRouter();
  const [reports, setReports] = useState<ReportLibraryItem[]>([]);
  const [incidentTypes, setIncidentTypes] = useState<string[]>([]);
  const [page, setPage] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [search, setSearch] = useState('');
  const [type, setType] = useState('all');
  const [severity, setSeverity] = useState('all');
  const [status, setStatus] = useState('all');
  const [datePreset, setDatePreset] = useState<DatePreset>('all');
  const [fromDate, setFromDate] = useState('');
  const [toDate, setToDate] = useState('');
  const [fromTime, setFromTime] = useState('');
  const [toTime, setToTime] = useState('');
  const [sort, setSort] = useState<Sort>('newest');
  const [busy, setBusy] = useState('');
  const [ready, setReady] = useState(false);
  const [debouncedSearch, setDebouncedSearch] = useState('');
  const restoredPosition = useRef(false);
  const loadSequence = useRef(0);

  async function load(signal?: AbortSignal) {
    const sequence = ++loadSequence.current;
    setLoading(true); setError('');
    try {
      const params = new URLSearchParams({ page: String(page), sort });
      if (debouncedSearch.trim()) params.set('search', debouncedSearch.trim());
      if (type !== 'all') params.set('type', type);
      if (severity !== 'all') params.set('severity', severity);
      if (status !== 'all') params.set('status', status);
      const today = new Date();
      const localDate = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
      if (datePreset === 'today') params.set('after', `${localDate(today)}T00:00:00`);
      if (datePreset === '7d' || datePreset === '30d') {
        const start = new Date(today.getFullYear(), today.getMonth(), today.getDate() - (datePreset === '7d' ? 6 : 29));
        params.set('after', `${localDate(start)}T00:00:00`);
      }
      if (datePreset === 'custom' && fromDate) params.set('after', `${fromDate}T00:00:00`);
      if (datePreset === 'custom' && toDate) params.set('before', `${toDate}T23:59:59.999`);
      if (fromTime) params.set('fromTime', fromTime);
      if (toTime) params.set('toTime', toTime);
      const response = await fetch(`/api/reports?${params}`, { cache: 'no-store', signal });
      const payload = (await response.json()) as { reports?: ReportLibraryItem[]; incidentTypes?: string[]; pagination?: { totalItems: number; totalPages: number }; error?: string };
      if (!response.ok || !payload.reports) throw new Error(payload.error || 'Could not load reports');
      setReports(payload.reports);
      setIncidentTypes(payload.incidentTypes || []);
      setTotalItems(payload.pagination?.totalItems || 0);
      setTotalPages(payload.pagination?.totalPages || 0);
      router.replace(`/reports?${params}`, { scroll: false });
    } catch (cause) { if (!(cause instanceof DOMException && cause.name === 'AbortError')) setError(cause instanceof Error ? cause.message : 'Could not load reports'); }
    finally { if (sequence === loadSequence.current) setLoading(false); }
  }

  useEffect(() => {
    const saved = window.sessionStorage.getItem('report-library-state');
    if (saved) {
      try {
        const state = JSON.parse(saved) as Record<string, string | number>;
        setSearch(String(state.search || '')); setType(query.get('type') || String(state.type || 'all'));
        setSeverity(query.get('severity') || String(state.severity || 'all')); setStatus(query.get('status') || String(state.status || 'all'));
        setDatePreset((state.datePreset || 'all') as DatePreset); setFromDate(String(state.fromDate || '')); setToDate(String(state.toDate || ''));
        setFromTime(String(state.fromTime || '')); setToTime(String(state.toTime || '')); setSort((state.sort || 'newest') as Sort);
        setPage(Number(query.get('page') || state.page || 1));
      } catch { /* ignore stale state */ }
    } else { setType(query.get('type') || 'all'); setSeverity(query.get('severity') || 'all'); setStatus(query.get('status') || 'all'); setPage(Number(query.get('page') || 1)); }
    setReady(true);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search), 300);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (!ready) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [ready, page, debouncedSearch, type, severity, status, datePreset, fromDate, toDate, fromTime, toTime, sort]);

  useEffect(() => {
    if (loading || restoredPosition.current) return;
    restoredPosition.current = true;
    try {
      const state = JSON.parse(window.sessionStorage.getItem('report-library-state') || '{}') as { scrollY?: number; reportId?: string };
      window.requestAnimationFrame(() => { if (state.reportId) document.getElementById(`report-${state.reportId}`)?.focus({ preventScroll: true }); window.scrollTo({ top: state.scrollY || 0 }); });
    } catch { /* ignore stale state */ }
  }, [loading]);

  function rememberPosition(item: ReportLibraryItem) {
    window.sessionStorage.setItem('report-library-state', JSON.stringify({ search, type, severity, status, datePreset, fromDate, toDate, fromTime, toTime, sort, page, scrollY: window.scrollY, reportId: item.reportId }));
  }

  async function updateStatus(item: ReportLibraryItem, nextStatus: ReviewStatus) {
    const reviewer = window.prompt(`Your name is required to mark this report ${statusLabel(nextStatus).toLowerCase()}.`);
    if (!reviewer?.trim()) return;
    if (nextStatus === 'verified' && !window.confirm('Verify this report as reviewed and accurate?')) return;
    setBusy(item.reportId);
    try {
      const response = await fetch(`/api/reports/${encodeURIComponent(item.videoId)}/review`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modelRunId: item.modelRunId, status: nextStatus, reviewedBy: reviewer }),
      });
      const payload = (await response.json()) as { error?: string; notified?: boolean };
      if (!response.ok) throw new Error(payload.error || 'Review update failed');
      setReports((current) => current.map((report) => report.reportId === item.reportId ? { ...report, status: nextStatus, editedBy: reviewer, verifiedBy: nextStatus === 'verified' ? reviewer : undefined } : report));
      if (payload.notified) window.alert('Verified. A high-severity notification was created.');
    } catch (cause) { window.alert(cause instanceof Error ? cause.message : 'Review update failed'); }
    finally { setBusy(''); }
  }

  async function reanalyze(item: ReportLibraryItem) {
    if (!item.sensorId || !item.r2Key) return window.alert('This report does not retain enough upload metadata to re-analyze.');
    setBusy(item.reportId);
    try {
      const response = await fetch('/api/analysis', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sensorId: item.sensorId, filepath: item.r2Key, filename: item.filename }) });
      const payload = (await response.json()) as { report?: AnalysisReport; error?: string };
      if (!response.ok || !payload.report) throw new Error(payload.error || 'Re-analysis failed');
      window.location.href = `/reports/${encodeURIComponent(payload.report.videoId)}?run=${encodeURIComponent(payload.report.modelRunId)}`;
    } catch (cause) { window.alert(cause instanceof Error ? cause.message : 'Re-analysis failed'); setBusy(''); }
  }

  async function deleteReport(item: ReportLibraryItem) {
    const deleteVideo = window.confirm('Delete the stored R2 video too?\n\nOK deletes the video and every report for it. Cancel keeps the video and deletes only this report.');
    const message = deleteVideo ? 'Permanently delete this video and all of its reports?' : 'Delete only this report? The R2 video will be kept.';
    if (!window.confirm(message)) return;
    setBusy(item.reportId);
    try {
      const response = await fetch(`/api/reports/${encodeURIComponent(item.videoId)}/delete?run=${encodeURIComponent(item.modelRunId)}&deleteVideo=${deleteVideo}`, { method: 'DELETE' });
      const payload = (await response.json()) as { error?: string };
      if (!response.ok) throw new Error(payload.error || 'Delete failed');
      if (reports.length === 1 && page > 1) setPage((current) => current - 1);
      else await load();
    } catch (cause) { window.alert(cause instanceof Error ? cause.message : 'Delete failed'); }
    finally { setBusy(''); }
  }

  return (
    <div className="mx-auto max-w-[1500px] px-6 pb-20 pt-8 lg:px-12">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-end sm:justify-between">
        <div><p className="font-mono text-xs uppercase tracking-[0.22em] text-moss">Decision history</p><h1 className="mt-3 text-4xl font-semibold tracking-[-0.04em] sm:text-5xl">Incident reports</h1><p className="mt-3 text-ink/55">Find, review, verify, and revisit every generated analysis.</p></div>
        <Link className="w-fit rounded-full bg-ink px-5 py-3 text-sm font-semibold text-white" href="/">+ Analyze video</Link>
      </div>

      <section className="mt-9 rounded-[1.5rem] border border-ink/10 bg-white p-4 shadow-panel" aria-label="Report filters">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
          <label className="xl:col-span-2"><span className="sr-only">Search reports</span><input className="control" onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Search reports and evidence…" type="search" value={search} /></label>
          <Select label="Incident type" onChange={(value) => { setType(value); setPage(1); }} value={type} options={[['all', 'All incident types'], ...incidentTypes.map((value) => [value, value])]} />
          <Select label="Severity" onChange={(value) => { setSeverity(value); setPage(1); }} value={severity} options={[['all', 'All severities'], ...[5, 4, 3, 2, 1].map((value) => [String(value), `Severity ${value}`])]} />
          <Select label="Review status" onChange={(value) => { setStatus(value); setPage(1); }} value={status} options={[['all', 'All review states'], ['unreviewed', 'Unreviewed'], ['under review', 'Under review'], ['verified', 'Verified']]} />
          <Select label="Sort reports" onChange={(value) => { setSort(value as Sort); setPage(1); }} value={sort} options={[['newest', 'Newest first'], ['oldest', 'Oldest first'], ['severity-high', 'Highest severity'], ['severity-low', 'Lowest severity'], ['confidence-high', 'Highest confidence'], ['confidence-low', 'Lowest confidence']]} />
        </div>
        <div className="mt-3 grid gap-3 border-t border-ink/8 pt-3 sm:grid-cols-2 lg:grid-cols-5">
          <Select label="Generated date" onChange={(value) => { setDatePreset(value as DatePreset); setPage(1); }} value={datePreset} options={[['all', 'Any date'], ['today', 'Today'], ['7d', 'Last 7 days'], ['30d', 'Last 30 days'], ['custom', 'Custom range']]} />
          <DateInput disabled={datePreset !== 'custom'} label="From date" onChange={(value) => { setFromDate(value); setPage(1); }} type="date" value={fromDate} />
          <DateInput disabled={datePreset !== 'custom'} label="To date" onChange={(value) => { setToDate(value); setPage(1); }} type="date" value={toDate} />
          <DateInput label="From time" onChange={(value) => { setFromTime(value); setPage(1); }} type="time" value={fromTime} />
          <DateInput label="To time" onChange={(value) => { setToTime(value); setPage(1); }} type="time" value={toTime} />
        </div>
      </section>

      <div className="mt-6 flex items-center justify-between text-sm text-ink/50"><span>{totalItems} {totalItems === 1 ? 'report' : 'reports'}</span>{(search || type !== 'all' || severity !== 'all' || status !== 'all' || datePreset !== 'all' || fromTime || toTime) && <button className="font-semibold text-moss" onClick={() => { setSearch(''); setType('all'); setSeverity('all'); setStatus('all'); setDatePreset('all'); setFromDate(''); setToDate(''); setFromTime(''); setToTime(''); setPage(1); }} type="button">Clear filters</button>}</div>
      {loading ? <LibrarySkeleton /> : error ? <div className="mt-8 rounded-2xl border border-clay/30 bg-white p-8 text-center"><p className="text-clay">{error}</p><button className="mt-4 font-semibold text-moss" onClick={() => void load()} type="button">Try again</button></div> : reports.length === 0 ? <div className="mt-8 rounded-2xl border border-dashed border-ink/20 p-14 text-center"><h2 className="text-xl font-semibold">No reports match these filters.</h2><p className="mt-2 text-sm text-ink/50">Clear the filters or analyze another video.</p></div> : <><div className="mt-5 grid gap-5 md:grid-cols-2 xl:grid-cols-3">{reports.map((item) => <ReportCard busy={busy === item.reportId} item={item} key={item.reportId} onDelete={deleteReport} onOpen={rememberPosition} onReanalyze={reanalyze} onStatus={updateStatus} />)}</div><Pagination page={page} totalItems={totalItems} totalPages={totalPages} onPage={setPage} /></>}
    </div>
  );
}

function ReportCard({ item, busy, onStatus, onReanalyze, onDelete, onOpen }: { item: ReportLibraryItem; busy: boolean; onStatus: (item: ReportLibraryItem, status: ReviewStatus) => void; onReanalyze: (item: ReportLibraryItem) => void; onDelete: (item: ReportLibraryItem) => void; onOpen: (item: ReportLibraryItem) => void }) {
  const href = `/reports/${encodeURIComponent(item.videoId)}?run=${encodeURIComponent(item.modelRunId)}`;
  const [thumbnailFailed, setThumbnailFailed] = useState(false);
  return <article className="overflow-hidden rounded-[1.5rem] border border-ink/10 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-panel focus:ring-2 focus:ring-signal" id={`report-${item.reportId}`} tabIndex={-1}>
    <ReportThumbnail failed={thumbnailFailed} onError={() => setThumbnailFailed(true)} severity={item.severity} status={item.status} thumbnailUrl={item.thumbnailUrl} />
    <div className="p-5"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-moss">{item.incident_type}</p><h2 className="mt-2 line-clamp-2 text-xl font-semibold tracking-[-0.025em]">{item.title}</h2></div><span className="shrink-0 text-sm font-semibold text-ink/55">{Math.round(item.confidence * 100)}%</span></div><p className="mt-3 line-clamp-3 text-sm leading-6 text-ink/60">{item.description}</p><p className="mt-4 truncate text-xs text-ink/40">{item.filename} · {new Date(item.generatedAt).toLocaleString()}</p><p className="mt-1 truncate text-[11px] text-ink/35">{item.model}</p>
      <div className="mt-5 flex flex-wrap gap-2"><Link className="rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white" href={href} onClick={() => onOpen(item)}>Open report</Link><button className="action" disabled={busy} onClick={() => onReanalyze(item)} type="button">Re-analyze</button><select aria-label={`Change review status for ${item.title}`} className="action bg-white" disabled={busy} onChange={(event) => onStatus(item, event.target.value as ReviewStatus)} value={item.status}><option value="unreviewed">Unreviewed</option><option value="under review">Under review</option><option value="verified">Verified</option></select><button className="action text-clay" disabled={busy} onClick={() => onDelete(item)} type="button">Delete</button></div>
    </div>
  </article>;
}

function ReportThumbnail({ thumbnailUrl, failed = false, onError, severity, status }: { thumbnailUrl?: string; failed?: boolean; onError?: () => void; severity: number; status: ReviewStatus }) {
  const view = reportThumbnailView(thumbnailUrl, failed);
  return <div className="relative aspect-video overflow-hidden bg-[#dfe3dc]" aria-label="Video screenshot preview">{view.kind === 'image' ? <img alt="" className="h-full w-full object-cover" loading={view.loading} onError={onError} src={view.src} /> : <><div className="absolute inset-0 bg-gradient-to-br from-white/35 to-transparent" /><div className="absolute inset-x-8 bottom-8 space-y-3"><div className="h-3 w-2/3 rounded-full bg-ink/15" /><div className="h-3 w-full rounded-full bg-ink/10" /><div className="h-3 w-4/5 rounded-full bg-ink/10" /></div><div className="absolute left-1/2 top-1/2 h-14 w-20 -translate-x-1/2 -translate-y-1/2 rounded-2xl bg-white/55 shadow-sm"><div className="absolute left-1/2 top-1/2 h-0 w-0 -translate-x-1/3 -translate-y-1/2 border-y-[10px] border-l-[16px] border-y-transparent border-l-ink/25" /></div></>}<span className={`absolute left-3 top-3 rounded-full px-3 py-1.5 text-xs font-bold ${severityClass(severity)}`}>Severity {severity}</span><span className="absolute right-3 top-3 rounded-full bg-white/90 px-3 py-1.5 text-xs font-semibold text-ink">{statusLabel(status)}</span></div>;
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: string[][]; onChange: (value: string) => void }) { return <label><span className="sr-only">{label}</span><select aria-label={label} className="control" onChange={(event) => onChange(event.target.value)} value={value}>{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>; }
function DateInput({ label, value, type, disabled, onChange }: { label: string; value: string; type: 'date' | 'time'; disabled?: boolean; onChange: (value: string) => void }) { return <label><span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-ink/40">{label}</span><input aria-label={label} className="control disabled:opacity-40" disabled={disabled} onChange={(event) => onChange(event.target.value)} type={type} value={value} /></label>; }
function Pagination({ page, totalItems, totalPages, onPage }: { page: number; totalItems: number; totalPages: number; onPage: (page: number) => void }) { const first = (page - 1) * 6 + 1; const last = Math.min(page * 6, totalItems); return <nav aria-label="Report pages" className="mt-8 flex flex-col items-center gap-3"><p className="text-sm font-semibold text-ink/65">Showing {first}–{last} of {totalItems} reports</p><div className="flex flex-wrap items-center justify-center gap-2"><button className="action" disabled={page <= 1} onClick={() => onPage(page - 1)} type="button">Previous</button>{Array.from({ length: totalPages }, (_, index) => index + 1).map((value) => <button aria-current={value === page ? 'page' : undefined} aria-label={`Page ${value}`} className={`grid h-9 min-w-9 place-items-center rounded-full text-sm font-semibold ${value === page ? 'bg-ink text-white' : 'border border-ink/10 bg-white'}`} key={value} onClick={() => onPage(value)} type="button">{value}</button>)}<button className="action" disabled={page >= totalPages} onClick={() => onPage(page + 1)} type="button">Next</button></div></nav>; }
function LibrarySkeleton() { return <div className="mt-5 grid gap-5 md:grid-cols-2 xl:grid-cols-3" role="status"><span className="sr-only">Loading reports</span>{[1, 2, 3, 4, 5, 6].map((value) => <div className="animate-pulse overflow-hidden rounded-[1.5rem] border border-ink/10 bg-white" key={value}><div className="aspect-video bg-ink/10" /><div className="space-y-3 p-5"><div className="h-5 w-2/3 rounded bg-ink/10" /><div className="h-4 rounded bg-ink/10" /><div className="h-4 w-4/5 rounded bg-ink/10" /></div></div>)}</div>; }
