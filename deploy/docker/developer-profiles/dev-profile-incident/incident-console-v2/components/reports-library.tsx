// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';

import type { AnalysisReport } from '@/lib/analysis/schema';
import type { ReportLibraryItem, ReviewStatus } from '@/lib/reports/storage';

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

function startOfDate(date: string): number | null {
  if (!date) return null;
  const value = new Date(`${date}T00:00:00`).getTime();
  return Number.isNaN(value) ? null : value;
}

export function ReportsLibrary() {
  const query = useSearchParams();
  const [reports, setReports] = useState<ReportLibraryItem[]>([]);
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

  async function load() {
    setLoading(true); setError('');
    try {
      const response = await fetch('/api/reports', { cache: 'no-store' });
      const payload = (await response.json()) as { reports?: ReportLibraryItem[]; error?: string };
      if (!response.ok || !payload.reports) throw new Error(payload.error || 'Could not load reports');
      setReports(payload.reports);
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not load reports'); }
    finally { setLoading(false); }
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
      } catch { /* ignore stale state */ }
    } else { setType(query.get('type') || 'all'); setSeverity(query.get('severity') || 'all'); setStatus(query.get('status') || 'all'); }
    void load();
  }, []);

  useEffect(() => {
    if (loading) return;
    try {
      const state = JSON.parse(window.sessionStorage.getItem('report-library-state') || '{}') as { scrollY?: number; reportId?: string };
      window.requestAnimationFrame(() => { if (state.reportId) document.getElementById(`report-${state.reportId}`)?.focus({ preventScroll: true }); window.scrollTo({ top: state.scrollY || 0 }); });
    } catch { /* ignore stale state */ }
  }, [loading]);

  function rememberPosition(item: ReportLibraryItem) {
    window.sessionStorage.setItem('report-library-state', JSON.stringify({ search, type, severity, status, datePreset, fromDate, toDate, fromTime, toTime, sort, scrollY: window.scrollY, reportId: item.reportId }));
  }

  const types = useMemo(() => Array.from(new Set(reports.map((item) => item.incident_type))).sort(), [reports]);
  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    let after: number | null = null;
    let before: number | null = null;
    if (datePreset === 'today') after = today;
    if (datePreset === '7d') after = today - 6 * 86400000;
    if (datePreset === '30d') after = today - 29 * 86400000;
    if (datePreset === 'custom') {
      after = startOfDate(fromDate);
      const end = startOfDate(toDate);
      before = end === null ? null : end + 86400000 - 1;
    }
    const result = reports.filter((item) => {
      const generated = new Date(item.generatedAt);
      const timestamp = generated.getTime();
      const minutes = generated.getHours() * 60 + generated.getMinutes();
      const fromMinutes = fromTime ? Number(fromTime.slice(0, 2)) * 60 + Number(fromTime.slice(3)) : null;
      const toMinutes = toTime ? Number(toTime.slice(0, 2)) * 60 + Number(toTime.slice(3)) : null;
      const haystack = `${item.title} ${item.filename} ${item.incident_type} ${item.description} ${item.searchableEvidence}`.toLowerCase();
      return (!needle || haystack.includes(needle))
        && (type === 'all' || item.incident_type === type)
        && (severity === 'all' || (severity === 'high' ? item.severity >= 4 : item.severity === Number(severity)))
        && (status === 'all' || item.status === status)
        && (after === null || timestamp >= after)
        && (before === null || timestamp <= before)
        && (fromMinutes === null || minutes >= fromMinutes)
        && (toMinutes === null || minutes <= toMinutes);
    });
    return result.sort((a, b) => {
      if (sort === 'oldest') return +new Date(a.generatedAt) - +new Date(b.generatedAt);
      if (sort === 'severity-high') return b.severity - a.severity;
      if (sort === 'severity-low') return a.severity - b.severity;
      if (sort === 'confidence-high') return b.confidence - a.confidence;
      if (sort === 'confidence-low') return a.confidence - b.confidence;
      return +new Date(b.generatedAt) - +new Date(a.generatedAt);
    });
  }, [reports, search, type, severity, status, datePreset, fromDate, toDate, fromTime, toTime, sort]);

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
      setReports((current) => current.filter((report) => deleteVideo ? report.videoId !== item.videoId : report.reportId !== item.reportId));
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
          <label className="xl:col-span-2"><span className="sr-only">Search reports</span><input className="control" onChange={(event) => setSearch(event.target.value)} placeholder="Search reports and evidence…" type="search" value={search} /></label>
          <Select label="Incident type" onChange={setType} value={type} options={[['all', 'All incident types'], ...types.map((value) => [value, value])]} />
          <Select label="Severity" onChange={setSeverity} value={severity} options={[['all', 'All severities'], ...[5, 4, 3, 2, 1].map((value) => [String(value), `Severity ${value}`])]} />
          <Select label="Review status" onChange={setStatus} value={status} options={[['all', 'All review states'], ['unreviewed', 'Unreviewed'], ['under review', 'Under review'], ['verified', 'Verified']]} />
          <Select label="Sort reports" onChange={(value) => setSort(value as Sort)} value={sort} options={[['newest', 'Newest first'], ['oldest', 'Oldest first'], ['severity-high', 'Highest severity'], ['severity-low', 'Lowest severity'], ['confidence-high', 'Highest confidence'], ['confidence-low', 'Lowest confidence']]} />
        </div>
        <div className="mt-3 grid gap-3 border-t border-ink/8 pt-3 sm:grid-cols-2 lg:grid-cols-5">
          <Select label="Generated date" onChange={(value) => setDatePreset(value as DatePreset)} value={datePreset} options={[['all', 'Any date'], ['today', 'Today'], ['7d', 'Last 7 days'], ['30d', 'Last 30 days'], ['custom', 'Custom range']]} />
          <DateInput disabled={datePreset !== 'custom'} label="From date" onChange={setFromDate} type="date" value={fromDate} />
          <DateInput disabled={datePreset !== 'custom'} label="To date" onChange={setToDate} type="date" value={toDate} />
          <DateInput label="From time" onChange={setFromTime} type="time" value={fromTime} />
          <DateInput label="To time" onChange={setToTime} type="time" value={toTime} />
        </div>
      </section>

      <div className="mt-6 flex items-center justify-between text-sm text-ink/50"><span>{filtered.length} {filtered.length === 1 ? 'report' : 'reports'}</span>{(search || type !== 'all' || severity !== 'all' || status !== 'all' || datePreset !== 'all' || fromTime || toTime) && <button className="font-semibold text-moss" onClick={() => { setSearch(''); setType('all'); setSeverity('all'); setStatus('all'); setDatePreset('all'); setFromDate(''); setToDate(''); setFromTime(''); setToTime(''); }} type="button">Clear filters</button>}</div>
      {loading ? <LibrarySkeleton /> : error ? <div className="mt-8 rounded-2xl border border-clay/30 bg-white p-8 text-center"><p className="text-clay">{error}</p><button className="mt-4 font-semibold text-moss" onClick={() => void load()} type="button">Try again</button></div> : filtered.length === 0 ? <div className="mt-8 rounded-2xl border border-dashed border-ink/20 p-14 text-center"><h2 className="text-xl font-semibold">No reports match these filters.</h2><p className="mt-2 text-sm text-ink/50">Clear the filters or analyze another video.</p></div> : <div className="mt-5 grid gap-5 md:grid-cols-2 xl:grid-cols-3">{filtered.map((item) => <ReportCard busy={busy === item.reportId} item={item} key={item.reportId} onDelete={deleteReport} onOpen={rememberPosition} onReanalyze={reanalyze} onStatus={updateStatus} />)}</div>}
    </div>
  );
}

function ReportCard({ item, busy, onStatus, onReanalyze, onDelete, onOpen }: { item: ReportLibraryItem; busy: boolean; onStatus: (item: ReportLibraryItem, status: ReviewStatus) => void; onReanalyze: (item: ReportLibraryItem) => void; onDelete: (item: ReportLibraryItem) => void; onOpen: (item: ReportLibraryItem) => void }) {
  const href = `/reports/${encodeURIComponent(item.videoId)}?run=${encodeURIComponent(item.modelRunId)}`;
  return <article className="overflow-hidden rounded-[1.5rem] border border-ink/10 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-panel focus:ring-2 focus:ring-signal" id={`report-${item.reportId}`} tabIndex={-1}>
    <div className="relative aspect-video bg-ink/90">{item.playbackUrl ? <video className="h-full w-full object-cover opacity-85" muted playsInline preload="metadata" src={item.playbackUrl} /> : <div className="grid h-full place-items-center text-sm text-white/50">Preview unavailable</div>}<span className={`absolute left-3 top-3 rounded-full px-3 py-1.5 text-xs font-bold ${severityClass(item.severity)}`}>Severity {item.severity}</span><span className="absolute right-3 top-3 rounded-full bg-white/90 px-3 py-1.5 text-xs font-semibold text-ink">{statusLabel(item.status)}</span></div>
    <div className="p-5"><div className="flex items-start justify-between gap-4"><div><p className="text-xs font-semibold uppercase tracking-[0.12em] text-moss">{item.incident_type}</p><h2 className="mt-2 line-clamp-2 text-xl font-semibold tracking-[-0.025em]">{item.title}</h2></div><span className="shrink-0 text-sm font-semibold text-ink/55">{Math.round(item.confidence * 100)}%</span></div><p className="mt-3 line-clamp-3 text-sm leading-6 text-ink/60">{item.description}</p><p className="mt-4 truncate text-xs text-ink/40">{item.filename} · {new Date(item.generatedAt).toLocaleString()}</p><p className="mt-1 truncate text-[11px] text-ink/35">{item.model}</p>
      <div className="mt-5 flex flex-wrap gap-2"><Link className="rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white" href={href} onClick={() => onOpen(item)}>Open report</Link><button className="action" disabled={busy} onClick={() => onReanalyze(item)} type="button">Re-analyze</button><select aria-label={`Change review status for ${item.title}`} className="action bg-white" disabled={busy} onChange={(event) => onStatus(item, event.target.value as ReviewStatus)} value={item.status}><option value="unreviewed">Unreviewed</option><option value="under review">Under review</option><option value="verified">Verified</option></select><button className="action text-clay" disabled={busy} onClick={() => onDelete(item)} type="button">Delete</button></div>
    </div>
  </article>;
}

function Select({ label, value, options, onChange }: { label: string; value: string; options: string[][]; onChange: (value: string) => void }) { return <label><span className="sr-only">{label}</span><select aria-label={label} className="control" onChange={(event) => onChange(event.target.value)} value={value}>{options.map(([key, text]) => <option key={key} value={key}>{text}</option>)}</select></label>; }
function DateInput({ label, value, type, disabled, onChange }: { label: string; value: string; type: 'date' | 'time'; disabled?: boolean; onChange: (value: string) => void }) { return <label><span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-ink/40">{label}</span><input aria-label={label} className="control disabled:opacity-40" disabled={disabled} onChange={(event) => onChange(event.target.value)} type={type} value={value} /></label>; }
function LibrarySkeleton() { return <div className="mt-5 grid gap-5 md:grid-cols-2 xl:grid-cols-3" role="status"><span className="sr-only">Loading reports</span>{[1, 2, 3].map((value) => <div className="animate-pulse overflow-hidden rounded-[1.5rem] border border-ink/10 bg-white" key={value}><div className="aspect-video bg-ink/10" /><div className="space-y-3 p-5"><div className="h-5 w-2/3 rounded bg-ink/10" /><div className="h-4 rounded bg-ink/10" /><div className="h-4 w-4/5 rounded bg-ink/10" /></div></div>)}</div>; }
