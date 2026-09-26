// SPDX-License-Identifier: Apache-2.0

'use client';

import { useRef, useState } from 'react';

import type { AnalysisReport } from '@/lib/analysis/schema';

function secondsLabel(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  return `${String(minutes).padStart(2, '0')}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`;
}

function severityStyle(level: number): string {
  if (level >= 4) return 'bg-[#ffe8df] text-[#9b3518]';
  if (level === 3) return 'bg-[#fff1c7] text-[#765300]';
  return 'bg-signal/15 text-moss';
}

export function IncidentReport({ report, onNewAnalysis }: { report: AnalysisReport & { originalReport?: AnalysisReport }; onNewAnalysis: () => void }) {
  const originalReport = report.originalReport || report;
  const [currentReport, setCurrentReport] = useState<AnalysisReport>(report);
  const videoRef = useRef<HTMLVideoElement>(null);
  const [copied, setCopied] = useState(false);
  const [reviewStatus, setReviewStatus] = useState(report.reviewStatus || 'unreviewed');
  const [reviewBusy, setReviewBusy] = useState(false);
  const [editingSummary, setEditingSummary] = useState(false);
  const [draft, setDraft] = useState<AnalysisReport>(report);
  const [editBusy, setEditBusy] = useState(false);
  const [editMessage, setEditMessage] = useState('');

  function seek(seconds: number) {
    if (!videoRef.current) return;
    videoRef.current.currentTime = seconds;
    void videoRef.current.play();
  }

  async function copyLink() {
    await navigator.clipboard.writeText(window.location.href);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1800);
  }

  async function changeReviewStatus(status: 'unreviewed' | 'under review' | 'verified') {
    const reviewer = window.prompt(`Your name is required to mark this report ${status}.`);
    if (!reviewer?.trim()) return;
    if (status === 'verified' && !window.confirm('Verify this report as reviewed and accurate?')) return;
    setReviewBusy(true);
    try {
      const response = await fetch(`/api/reports/${encodeURIComponent(report.videoId)}/review`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modelRunId: report.modelRunId, status, reviewedBy: reviewer }),
      });
      const payload = (await response.json()) as { error?: string; notified?: boolean };
      if (!response.ok) throw new Error(payload.error || 'Review update failed');
      setReviewStatus(status);
      if (payload.notified) window.alert('Verified. A high-severity notification was created.');
    } catch (error) {
      window.alert(error instanceof Error ? error.message : 'Review update failed');
    } finally {
      setReviewBusy(false);
    }
  }

  async function saveSummary() {
    if (!draft.description.trim() || editBusy) return;
    if (reviewStatus === 'verified' && !window.confirm('This report is verified. Save this edited summary anyway?')) return;
    setEditBusy(true);
    setEditMessage('Saving…');
    try {
      const response = await fetch(`/api/reports/${encodeURIComponent(report.videoId)}/edit`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          modelRunId: report.modelRunId,
          originalReport: Object.fromEntries(Object.entries(originalReport).filter(([key]) => !['videoId', 'modelRunId', 'reportId', 'filename', 'playbackUrl', 'model', 'generatedAt', 'promptVersion', 'rawModelOutput', 'normalizedModelOutput', 'reviewStatus', 'verifiedBy', 'verifiedAt', 'originalReport'].includes(key))),
          editedReport: Object.fromEntries(Object.entries(draft).filter(([key]) => !['videoId', 'modelRunId', 'reportId', 'filename', 'playbackUrl', 'model', 'generatedAt', 'promptVersion', 'rawModelOutput', 'normalizedModelOutput', 'reviewStatus', 'verifiedBy', 'verifiedAt', 'originalReport'].includes(key))),
        }),
      });
      const payload = (await response.json()) as { error?: string };
      if (!response.ok) throw new Error(payload.error || 'Save failed');
      setCurrentReport({ ...currentReport, ...draft });
      setEditMessage('');
      setEditingSummary(false);
    } catch (error) {
      setEditMessage(error instanceof Error ? error.message : 'Save failed');
    } finally {
      setEditBusy(false);
    }
  }

  return (
    <article className="report-sheet overflow-hidden rounded-[2rem] border border-ink/10 bg-white shadow-panel">
      <div className="print-hidden flex flex-wrap items-center justify-between gap-3 border-b border-ink/10 bg-white px-6 py-3 text-xs">
        <span className="text-ink/45">Report {report.reportId}</span>
        <div className="flex gap-4">
          <button className="font-semibold text-moss" onClick={copyLink} type="button">{copied ? 'Link copied' : 'Copy link'}</button>
          <button className="font-semibold text-moss" onClick={() => window.print()} type="button">Print report</button>
          <button className="font-semibold text-moss" onClick={onNewAnalysis} type="button">New analysis</button>
        </div>
      </div>
      <header className="border-b border-ink/10 bg-[#eef2e9] p-6 sm:p-8">
        <div className="flex flex-col gap-5 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-moss">Analysis complete</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">{currentReport.title || 'Incident Report'}</h2>
            <p className="mt-3 text-sm text-ink/55">
              {currentReport.incident_type}{currentReport.location ? ` · ${currentReport.location}` : ''} · {report.filename}
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <span className={`rounded-full px-4 py-2 text-sm font-bold ${severityStyle(currentReport.severity)}`}>Severity {currentReport.severity}/5</span>
            <span className="rounded-full bg-white px-4 py-2 text-sm font-semibold text-ink/65">{Math.round(currentReport.confidence * 100)}% confidence</span>
          </div>
        </div>
      </header>

      <section className="print-hidden flex flex-col gap-3 border-b border-ink/10 bg-white px-6 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <div><p className="text-xs font-bold uppercase tracking-[0.12em] text-ink/40">Human review</p><p className="mt-1 text-sm text-ink/60">Current status: <strong className="text-ink">{reviewStatus === 'under review' ? 'Under review' : reviewStatus[0].toUpperCase() + reviewStatus.slice(1)}</strong></p></div>
        <div className="flex flex-wrap gap-2">
          <button className="action" disabled={editBusy || editingSummary} onClick={() => { setDraft(currentReport); setEditMessage(''); setEditingSummary(true); }} type="button">{editingSummary ? 'Editing report' : 'Edit report'}</button>
          {reviewStatus !== 'verified' && <button className="rounded-full bg-moss px-4 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={reviewBusy} onClick={() => void changeReviewStatus('verified')} type="button">Verify report</button>}
          {reviewStatus !== 'unreviewed' && <button className="action" disabled={reviewBusy} onClick={() => void changeReviewStatus('unreviewed')} type="button">Reset review</button>}
        </div>
      </section>

      <div className="grid lg:grid-cols-[1.08fr_0.92fr]">
        <div className="border-b border-ink/10 p-5 lg:border-b-0 lg:border-r sm:p-7">
          <video className="aspect-video w-full rounded-2xl bg-black object-contain" controls ref={videoRef} src={report.playbackUrl} />
          <div className="mt-6">
            <h3 className="text-sm font-bold uppercase tracking-[0.12em] text-ink/45">Event timeline</h3>
            {currentReport.timeline.length ? <ol className="mt-3 space-y-2">
              {currentReport.timeline.map((event, index) => (
                <li key={`${event.start_seconds}-${index}`}>
                  <button aria-label={`Play video from ${secondsLabel(event.start_seconds)}: ${event.description}`} className="group flex w-full gap-4 rounded-xl border border-ink/8 p-3 text-left transition hover:border-moss/30 hover:bg-moss/5 focus:outline-none focus:ring-2 focus:ring-signal" onClick={() => seek(event.start_seconds)} type="button">
                    <span className="font-mono text-xs font-bold text-moss">{secondsLabel(event.start_seconds)}</span>
                    <span className="text-sm leading-5 text-ink/70 group-hover:text-ink">{event.description}</span>
                  </button>
                </li>
              ))}
            </ol> : <p className="mt-3 rounded-xl border border-dashed border-ink/15 p-4 text-sm text-ink/45">No timestamped events were returned for this analysis.</p>}
          </div>
        </div>

        <div className="p-6 sm:p-8">
          <section>
            <h3 className="text-sm font-bold uppercase tracking-[0.12em] text-ink/45">Executive summary</h3>
            {editingSummary ? (
              <div className="mt-4 grid items-start gap-4 xl:grid-cols-2">
                <div className="rounded-2xl border border-ink/10 bg-canvas/60 p-4">
                  <p className="text-xs font-bold uppercase tracking-[0.12em] text-ink/40">Original AI report</p>
                  <OriginalReport report={originalReport} />
                </div>
                <div className="rounded-2xl border border-moss/25 bg-white p-4 shadow-sm">
                  <p className="text-xs font-bold uppercase tracking-[0.12em] text-moss">Your editable report</p>
                  <label className="mt-3 block text-xs font-bold">Title<input className="control mt-1" onChange={(e) => setDraft({ ...draft, title: e.target.value })} value={draft.title} /></label>
                  <div className="mt-3 grid grid-cols-2 gap-2"><label className="text-xs font-bold">Incident type<input className="control mt-1" onChange={(e) => setDraft({ ...draft, incident_type: e.target.value })} value={draft.incident_type} /></label><label className="text-xs font-bold">Location<input className="control mt-1" onChange={(e) => setDraft({ ...draft, location: e.target.value })} value={draft.location} /></label><label className="text-xs font-bold">Severity<input className="control mt-1" max={5} min={1} onChange={(e) => setDraft({ ...draft, severity: Number(e.target.value) })} type="number" value={draft.severity} /></label><label className="text-xs font-bold">Confidence<input className="control mt-1" max={1} min={0} onChange={(e) => setDraft({ ...draft, confidence: Number(e.target.value) })} step="0.01" type="number" value={draft.confidence} /></label><label className="text-xs font-bold">Start<input className="control mt-1" onChange={(e) => setDraft({ ...draft, incident_start: e.target.value })} value={draft.incident_start} /></label><label className="text-xs font-bold">End<input className="control mt-1" onChange={(e) => setDraft({ ...draft, incident_end: e.target.value })} value={draft.incident_end} /></label><label className="text-xs font-bold">Duration (seconds)<input className="control mt-1" min={0} onChange={(e) => setDraft({ ...draft, duration_seconds: e.target.value ? Number(e.target.value) : null })} type="number" value={draft.duration_seconds ?? ''} /></label><label className="flex items-center gap-2 pt-5 text-xs font-bold"><input checked={draft.incident_start_confirmed} onChange={(e) => setDraft({ ...draft, incident_start_confirmed: e.target.checked })} type="checkbox" />Start time confirmed</label></div>
                  <label className="mt-3 block text-xs font-bold">Executive summary<textarea className="control mt-1 min-h-[100px]" onChange={(e) => setDraft({ ...draft, description: e.target.value })} value={draft.description} /></label>
                  <label className="mt-3 block text-xs font-bold">Severity reason<textarea className="control mt-1 min-h-[70px]" onChange={(e) => setDraft({ ...draft, severity_reason: e.target.value })} value={draft.severity_reason} /></label>
                  <label className="mt-3 block text-xs font-bold">People and entities<div className="mt-2 space-y-2">{draft.persons.map((person, index) => <div className="rounded-xl border border-ink/10 p-3" key={index}><input aria-label={`Person or entity ${index + 1} description`} className="control" onChange={(e) => setDraft({ ...draft, persons: patchItem(draft.persons, index, { description: e.target.value }) })} placeholder="Description" value={person.description} /><input aria-label={`Person or entity ${index + 1} actions`} className="control mt-2" onChange={(e) => setDraft({ ...draft, persons: patchItem(draft.persons, index, { actions: e.target.value }) })} placeholder="Actions" value={person.actions} /><RemoveButton onClick={() => setDraft({ ...draft, persons: draft.persons.filter((_, i) => i !== index) })} /></div>)}<AddButton onClick={() => setDraft({ ...draft, persons: [...draft.persons, { description: '', actions: '' }] })} /></div></label>
                  <label className="mt-3 block text-xs font-bold">Instruments<div className="mt-2 space-y-2">{draft.instruments.map((item, index) => <div className="rounded-xl border border-ink/10 p-3" key={index}><input className="control" onChange={(e) => setDraft({ ...draft, instruments: patchItem(draft.instruments, index, { name: e.target.value }) })} placeholder="Name" value={item.name} /><textarea className="control mt-2" onChange={(e) => setDraft({ ...draft, instruments: patchItem(draft.instruments, index, { description: e.target.value }) })} placeholder="Description" value={item.description} /><input className="control mt-2" max={5} min={1} onChange={(e) => setDraft({ ...draft, instruments: patchItem(draft.instruments, index, { threat_level: e.target.value ? Number(e.target.value) : null }) })} placeholder="Threat level" type="number" value={item.threat_level ?? ''} /><RemoveButton onClick={() => setDraft({ ...draft, instruments: draft.instruments.filter((_, i) => i !== index) })} /></div>)}<AddButton onClick={() => setDraft({ ...draft, instruments: [...draft.instruments, { name: '', description: '', threat_level: null }] })} /></div></label>
                  <label className="mt-3 block text-xs font-bold">Assets<div className="mt-2 space-y-2">{draft.assets.map((item, index) => <div className="rounded-xl border border-ink/10 p-3" key={index}><input className="control" onChange={(e) => setDraft({ ...draft, assets: patchItem(draft.assets, index, { name: e.target.value }) })} placeholder="Name" value={item.name} /><textarea className="control mt-2" onChange={(e) => setDraft({ ...draft, assets: patchItem(draft.assets, index, { description: e.target.value }) })} placeholder="Description" value={item.description} /><RemoveButton onClick={() => setDraft({ ...draft, assets: draft.assets.filter((_, i) => i !== index) })} /></div>)}<AddButton onClick={() => setDraft({ ...draft, assets: [...draft.assets, { name: '', description: '' }] })} /></div></label>
                  <label className="mt-3 block text-xs font-bold">Timeline<div className="mt-2 space-y-2">{draft.timeline.map((item, index) => <div className="rounded-xl border border-ink/10 p-3" key={index}><div className="grid grid-cols-2 gap-2"><input aria-label={`Timeline event ${index + 1} start time`} className="control" onChange={(e) => setDraft({ ...draft, timeline: patchItem(draft.timeline, index, { start_seconds: Number(e.target.value) }) })} type="number" value={item.start_seconds} /><input aria-label={`Timeline event ${index + 1} end time`} className="control" onChange={(e) => setDraft({ ...draft, timeline: patchItem(draft.timeline, index, { end_seconds: Number(e.target.value) }) })} type="number" value={item.end_seconds ?? ''} /></div><textarea className="control mt-2" onChange={(e) => setDraft({ ...draft, timeline: patchItem(draft.timeline, index, { description: e.target.value }) })} placeholder="Event description" value={item.description} /><RemoveButton onClick={() => setDraft({ ...draft, timeline: draft.timeline.filter((_, i) => i !== index) })} /></div>)}<AddButton onClick={() => setDraft({ ...draft, timeline: [...draft.timeline, { start_seconds: 0, end_seconds: null, description: '' }] })} /></div></label>
                  <label className="mt-3 block text-xs font-bold">Uncertainties<div className="mt-2 space-y-2">{draft.uncertainties.map((item, index) => <div className="flex gap-2" key={index}><input className="control" onChange={(e) => setDraft({ ...draft, uncertainties: draft.uncertainties.map((value, i) => i === index ? e.target.value : value) })} value={item} /><RemoveButton onClick={() => setDraft({ ...draft, uncertainties: draft.uncertainties.filter((_, i) => i !== index) })} /></div>)}<AddButton onClick={() => setDraft({ ...draft, uncertainties: [...draft.uncertainties, ''] })} /></div></label>
                  <div className="mt-4 flex flex-wrap items-center gap-2"><button className="rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={editBusy || !draft.description.trim()} onClick={() => void saveSummary()} type="button">{editBusy ? 'Saving…' : 'Save edited report'}</button><button className="action" disabled={editBusy} onClick={() => { setDraft(currentReport); setEditMessage(''); setEditingSummary(false); }} type="button">Cancel</button></div>
                  {editMessage && <p aria-live="polite" className="mt-3 text-xs text-ink/55">{editMessage}</p>}
                </div>
              </div>
            ) : <p className="mt-3 whitespace-pre-wrap text-base leading-7 text-ink/75">{currentReport.description}</p>}
          </section>
          <section className="mt-7 rounded-2xl bg-canvas p-5">
            <h3 className="font-semibold">Why severity {currentReport.severity}</h3>
            <p className="mt-2 text-sm leading-6 text-ink/60">{currentReport.severity_reason}</p>
          </section>

          <div className="mt-7 grid gap-5 sm:grid-cols-2">
            <EvidenceGroup
              title="People and entities"
              empty="None identified"
              items={currentReport.persons.map((item) => [item.description, item.actions].filter(Boolean).join(': ') || item.description || 'Person')}
            />
            <EvidenceGroup
              title="Instruments"
              empty="None identified"
              items={currentReport.instruments.map((item) => `${item.name}${item.threat_level ? ` (threat: ${item.threat_level}/5)` : ''}: ${item.description}`)}
            />
            <EvidenceGroup
              title="Assets"
              empty="None identified"
              items={currentReport.assets.map((item) => `${item.name}: ${item.description}`)}
            />
            <EvidenceGroup
              title="Uncertainties"
              empty="No material uncertainty reported"
              items={currentReport.uncertainties}
            />
          </div>
        </div>
      </div>

      <section className="border-t border-ink/10 px-6 py-6 sm:px-8">
        <details className="group rounded-2xl border border-ink/10 bg-canvas/60">
          <summary className="cursor-pointer list-none px-5 py-4 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-inset focus:ring-signal">
            <span className="flex items-center justify-between"><span>Analysis provenance and diagnostics</span><span className="text-ink/35 group-open:rotate-180">⌄</span></span>
          </summary>
          <div className="border-t border-ink/10 px-5 py-5">
            <dl className="grid gap-x-6 gap-y-4 text-xs sm:grid-cols-2 lg:grid-cols-4">
              <Provenance label="Model" value={report.model} />
              <Provenance label="Prompt version" value={report.promptVersion || 'Legacy v2 prompt'} />
              <Provenance label="Model run" value={report.modelRunId} />
              <Provenance label="Generated" value={new Date(report.generatedAt).toLocaleString()} />
            </dl>
              {report.rawModelOutput ? (
              <div className="mt-6">
                <h4 className="text-xs font-bold uppercase tracking-[0.12em] text-ink/45">Raw model output</h4>
                <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-xl bg-ink p-4 font-mono text-xs leading-5 text-white/75">{report.rawModelOutput}</pre>
                {report.normalizedModelOutput && report.normalizedModelOutput !== report.rawModelOutput && <p className="mt-2 text-xs text-clay">The raw response required a second formatting pass before schema validation.</p>}
              </div>
            ) : <p className="mt-6 text-xs italic text-ink/40">Raw output was not retained for this earlier model run.</p>}
          </div>
        </details>
      </section>

      <footer className="flex flex-col gap-3 border-t border-ink/10 bg-canvas/70 px-6 py-4 text-xs text-ink/45 sm:flex-row sm:items-center sm:justify-between">
        <span>{report.model} · {report.promptVersion || 'legacy prompt'} · {new Date(report.generatedAt).toLocaleString()}</span>
        <button className="font-semibold text-moss" onClick={onNewAnalysis} type="button">Analyze another video</button>
      </footer>
    </article>
  );
}

function Provenance({ label, value }: { label: string; value: string }) {
  return <div><dt className="font-bold uppercase tracking-[0.1em] text-ink/40">{label}</dt><dd className="mt-1 break-all font-mono text-ink/70">{value}</dd></div>;
}

function OriginalReport({ report }: { report: AnalysisReport }) {
  return <div className="mt-3 max-h-[70vh] space-y-4 overflow-auto pr-1 text-sm leading-6 text-ink/65">
    <div><strong>Title:</strong> {report.title || '—'}<br /><strong>Incident type:</strong> {report.incident_type}<br /><strong>Location:</strong> {report.location || '—'}<br /><strong>Severity:</strong> {report.severity}/5 · <strong>Confidence:</strong> {Math.round(report.confidence * 100)}%<br /><strong>Time:</strong> {report.incident_start}–{report.incident_end} · {report.duration_seconds ?? 'Unknown'} seconds</div>
    <div><strong>Executive summary</strong><p className="whitespace-pre-wrap">{report.description || '—'}</p></div>
    <div><strong>Severity reason</strong><p className="whitespace-pre-wrap">{report.severity_reason || '—'}</p></div>
    <div><strong>People and entities</strong>{report.persons.length ? report.persons.map((item, index) => <p key={index}>{item.description}{item.actions ? ` — ${item.actions}` : ''}</p>) : <p>None identified</p>}</div>
    <div><strong>Instruments</strong>{report.instruments.length ? report.instruments.map((item, index) => <p key={index}>{item.name}: {item.description}{item.threat_level ? ` (threat ${item.threat_level}/5)` : ''}</p>) : <p>None identified</p>}</div>
    <div><strong>Assets</strong>{report.assets.length ? report.assets.map((item, index) => <p key={index}>{item.name}: {item.description}</p>) : <p>None identified</p>}</div>
    <div><strong>Timeline</strong>{report.timeline.length ? report.timeline.map((item, index) => <p key={index}>{secondsLabel(item.start_seconds)}{item.end_seconds == null ? '' : `–${secondsLabel(item.end_seconds)}`} · {item.description}</p>) : <p>No timestamped events</p>}</div>
    <div><strong>Uncertainties</strong>{report.uncertainties.length ? report.uncertainties.map((item, index) => <p key={index}>{item}</p>) : <p>None reported</p>}</div>
  </div>;
}

function patchItem<T>(items: T[], index: number, patch: Partial<T>): T[] {
  return items.map((item, itemIndex) => itemIndex === index ? { ...item, ...patch } : item);
}

function AddButton({ onClick }: { onClick: () => void }) {
  return <button className="mt-2 rounded-full border border-ink/15 px-3 py-1.5 text-xs font-semibold text-moss" onClick={onClick} type="button">Add item</button>;
}

function RemoveButton({ onClick }: { onClick: () => void }) {
  return <button className="mt-2 rounded-full px-3 py-1.5 text-xs font-semibold text-clay" onClick={onClick} type="button">Remove</button>;
}

function EvidenceGroup({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  return (
    <section>
      <h3 className="text-xs font-bold uppercase tracking-[0.12em] text-ink/45">{title}</h3>
      {items.length ? (
        <ul className="mt-2 space-y-2 text-sm leading-5 text-ink/65">
          {items.map((item, index) => <li className="border-l-2 border-signal/50 pl-3" key={`${item}-${index}`}>{item}</li>)}
        </ul>
      ) : <p className="mt-2 text-sm italic text-ink/35">{empty}</p>}
    </section>
  );
}
