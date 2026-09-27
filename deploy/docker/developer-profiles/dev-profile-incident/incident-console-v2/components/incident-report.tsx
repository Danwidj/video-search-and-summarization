// SPDX-License-Identifier: Apache-2.0

'use client';

import { useRef, useState } from 'react';

import {
  confidenceLabel,
  contractPart,
  ENTITY_TYPES,
  INCIDENT_TYPES,
  secondsLabel,
  type AnalysisReport,
  type ContractIncident,
  type IncidentContractReport,
} from '@/lib/analysis/contract-types';

function severityStyle(level: number): string {
  if (level >= 4) return 'bg-[#ffe8df] text-[#9b3518]';
  if (level === 3) return 'bg-[#fff1c7] text-[#765300]';
  return 'bg-signal/15 text-moss';
}

/** Renumber E/I/A ids sequentially after edits and keep instrument holders pointing at the same entity. */
export function renumberIds(report: IncidentContractReport): IncidentContractReport {
  const entityMap = new Map(report.entities.map((entity, index) => [entity.entity_id, `E${index + 1}`]));
  return {
    ...report,
    incident: { ...report.incident, duration: Math.max(0, report.incident.end_timestamp - report.incident.start_timestamp) },
    entities: report.entities.map((entity, index) => ({ ...entity, entity_id: `E${index + 1}` })),
    instruments: report.instruments.map((item, index) => ({
      ...item,
      instrument_id: `I${index + 1}`,
      entity_id: item.entity_id === null ? null : entityMap.get(item.entity_id) ?? null,
    })),
    assets: report.assets.map((item, index) => ({ ...item, asset_id: `A${index + 1}` })),
  };
}

type ReportWithOriginal = AnalysisReport & { originalReport?: AnalysisReport };

export function IncidentReport({ report, onNewAnalysis }: { report: ReportWithOriginal; onNewAnalysis: () => void }) {
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
  const { incident } = currentReport;

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

  function setIncident(patch: Partial<ContractIncident>) {
    setDraft({ ...draft, incident: { ...draft.incident, ...patch } });
  }

  async function saveReport() {
    if (!draft.incident.description.trim() || editBusy) return;
    if (reviewStatus === 'verified' && !window.confirm('This report is verified. Save this edited report anyway?')) return;
    setEditBusy(true);
    setEditMessage('Saving…');
    try {
      const edited = renumberIds(contractPart(draft));
      const response = await fetch(`/api/reports/${encodeURIComponent(report.videoId)}/edit`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modelRunId: report.modelRunId, editedReport: edited }),
      });
      const payload = (await response.json()) as { error?: string; report?: IncidentContractReport };
      if (!response.ok) throw new Error(payload.error || 'Save failed');
      setCurrentReport({ ...currentReport, ...(payload.report ?? edited) });
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
            <h2 className="mt-3 text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">{incident.title || 'Incident Report'}</h2>
            <p className="mt-3 text-sm text-ink/55">
              {incident.type}{incident.location ? ` · ${incident.location}` : ''} · {report.filename}
            </p>
            {currentReport.legacy && <p className="mt-2 text-xs text-clay">Created before the incident contract; shown read-only in the current format.</p>}
          </div>
          <div className="flex shrink-0 gap-2">
            <span className={`rounded-full px-4 py-2 text-sm font-bold ${severityStyle(incident.severity_level)}`}>Severity {incident.severity_level}/5</span>
            <span className="rounded-full bg-white px-4 py-2 text-sm font-semibold text-ink/65">{confidenceLabel(incident.confidence_score)}</span>
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
          <p className="mt-3 text-xs text-ink/50">Incident {secondsLabel(incident.start_timestamp)}–{secondsLabel(incident.end_timestamp)} · {incident.duration} seconds</p>
          <div className="mt-6">
            <h3 className="text-sm font-bold uppercase tracking-[0.12em] text-ink/45">Event timeline</h3>
            {currentReport.timeline.length ? <ol className="mt-3 space-y-2">
              {currentReport.timeline.map((event, index) => (
                <li key={`${event.start_seconds}-${index}`}>
                  <button aria-label={`Play video from ${secondsLabel(event.start_seconds)}: ${event.description}`} className="group flex w-full gap-4 rounded-xl border border-ink/8 p-3 text-left transition hover:border-moss/30 hover:bg-moss/5 focus:outline-none focus:ring-2 focus:ring-signal" onClick={() => seek(event.start_seconds)} type="button">
                    <span className="font-mono text-xs font-bold text-moss">{secondsLabel(event.start_seconds)}{event.end_seconds === null ? '' : `–${secondsLabel(event.end_seconds)}`}</span>
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
                  <label className="mt-3 block text-xs font-bold">Title<input className="control mt-1" onChange={(e) => setIncident({ title: e.target.value })} value={draft.incident.title} /></label>
                  <div className="mt-3 grid grid-cols-2 gap-2">
                    <label className="text-xs font-bold">Incident type<select className="control mt-1" onChange={(e) => setIncident({ type: e.target.value })} value={draft.incident.type}>{!INCIDENT_TYPES.includes(draft.incident.type as typeof INCIDENT_TYPES[number]) && <option value={draft.incident.type}>{draft.incident.type || 'Choose a type'}</option>}{INCIDENT_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select></label>
                    <label className="text-xs font-bold">Location<input className="control mt-1" onChange={(e) => setIncident({ location: e.target.value || null })} value={draft.incident.location ?? ''} /></label>
                    <label className="text-xs font-bold">Severity<input className="control mt-1" max={5} min={1} onChange={(e) => setIncident({ severity_level: Number(e.target.value) })} type="number" value={draft.incident.severity_level} /></label>
                    <label className="text-xs font-bold">Confidence (0–1, blank if none)<input className="control mt-1" max={1} min={0} onChange={(e) => setIncident({ confidence_score: e.target.value === '' ? null : Number(e.target.value) })} step="0.01" type="number" value={draft.incident.confidence_score ?? ''} /></label>
                    <label className="text-xs font-bold">Start (seconds)<input className="control mt-1" min={0} onChange={(e) => setIncident({ start_timestamp: Number(e.target.value) })} type="number" value={draft.incident.start_timestamp} /></label>
                    <label className="text-xs font-bold">End (seconds)<input className="control mt-1" min={0} onChange={(e) => setIncident({ end_timestamp: Number(e.target.value) })} type="number" value={draft.incident.end_timestamp} /></label>
                    <p className="col-span-2 text-xs text-ink/50">Duration is calculated: {Math.max(0, draft.incident.end_timestamp - draft.incident.start_timestamp)} seconds.</p>
                  </div>
                  <label className="mt-3 block text-xs font-bold">Executive summary<textarea className="control mt-1 min-h-[100px]" onChange={(e) => setIncident({ description: e.target.value })} value={draft.incident.description} /></label>
                  <label className="mt-3 block text-xs font-bold">Severity reason<textarea className="control mt-1 min-h-[70px]" onChange={(e) => setIncident({ severity_reason: e.target.value })} value={draft.incident.severity_reason} /></label>
                  <label className="mt-3 block text-xs font-bold">People and entities<div className="mt-2 space-y-2">{draft.entities.map((entity, index) => <div className="rounded-xl border border-ink/10 p-3" key={index}><select aria-label={`Entity ${index + 1} type`} className="control" onChange={(e) => setDraft({ ...draft, entities: patchItem(draft.entities, index, { type: e.target.value }) })} value={entity.type}>{ENTITY_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}</select><textarea aria-label={`Entity ${index + 1} description`} className="control mt-2" onChange={(e) => setDraft({ ...draft, entities: patchItem(draft.entities, index, { description: e.target.value }) })} placeholder="Appearance, actions and role" value={entity.description} /><RemoveButton onClick={() => setDraft({ ...draft, entities: draft.entities.filter((_, i) => i !== index), instruments: draft.instruments.map((item) => item.entity_id === entity.entity_id ? { ...item, entity_id: null } : item) })} /></div>)}<AddButton onClick={() => setDraft({ ...draft, entities: [...draft.entities, { entity_id: `new-${Date.now()}`, type: 'human', description: '' }] })} /></div></label>
                  <label className="mt-3 block text-xs font-bold">Instruments<div className="mt-2 space-y-2">{draft.instruments.map((item, index) => <div className="rounded-xl border border-ink/10 p-3" key={index}><input className="control" onChange={(e) => setDraft({ ...draft, instruments: patchItem(draft.instruments, index, { name: e.target.value }) })} placeholder="Name" value={item.name} /><textarea className="control mt-2" onChange={(e) => setDraft({ ...draft, instruments: patchItem(draft.instruments, index, { description: e.target.value }) })} placeholder="Description" value={item.description} /><div className="mt-2 grid grid-cols-2 gap-2"><select aria-label={`Instrument ${index + 1} holder`} className="control" onChange={(e) => setDraft({ ...draft, instruments: patchItem(draft.instruments, index, { entity_id: e.target.value || null }) })} value={item.entity_id ?? ''}><option value="">Holder unknown</option>{draft.entities.map((entity, entityIndex) => <option key={entity.entity_id} value={entity.entity_id}>Entity {entityIndex + 1}</option>)}</select><input aria-label={`Instrument ${index + 1} threat level`} className="control" max={5} min={1} onChange={(e) => setDraft({ ...draft, instruments: patchItem(draft.instruments, index, { threat_level: Number(e.target.value) }) })} type="number" value={item.threat_level} /></div><RemoveButton onClick={() => setDraft({ ...draft, instruments: draft.instruments.filter((_, i) => i !== index) })} /></div>)}<AddButton onClick={() => setDraft({ ...draft, instruments: [...draft.instruments, { instrument_id: '', entity_id: null, name: '', description: '', threat_level: 1 }] })} /></div></label>
                  <label className="mt-3 block text-xs font-bold">Assets<div className="mt-2 space-y-2">{draft.assets.map((item, index) => <div className="rounded-xl border border-ink/10 p-3" key={index}><input className="control" onChange={(e) => setDraft({ ...draft, assets: patchItem(draft.assets, index, { name: e.target.value }) })} placeholder="Name" value={item.name} /><textarea className="control mt-2" onChange={(e) => setDraft({ ...draft, assets: patchItem(draft.assets, index, { description: e.target.value }) })} placeholder="Description" value={item.description} /><RemoveButton onClick={() => setDraft({ ...draft, assets: draft.assets.filter((_, i) => i !== index) })} /></div>)}<AddButton onClick={() => setDraft({ ...draft, assets: [...draft.assets, { asset_id: '', name: '', description: '' }] })} /></div></label>
                  <label className="mt-3 block text-xs font-bold">Timeline (must fall within the incident start and end)<div className="mt-2 space-y-2">{draft.timeline.map((item, index) => <div className="rounded-xl border border-ink/10 p-3" key={index}><div className="grid grid-cols-2 gap-2"><input aria-label={`Timeline event ${index + 1} start time`} className="control" min={0} onChange={(e) => setDraft({ ...draft, timeline: patchItem(draft.timeline, index, { start_seconds: Number(e.target.value) }) })} type="number" value={item.start_seconds} /><input aria-label={`Timeline event ${index + 1} end time`} className="control" min={0} onChange={(e) => setDraft({ ...draft, timeline: patchItem(draft.timeline, index, { end_seconds: e.target.value === '' ? null : Number(e.target.value) }) })} type="number" value={item.end_seconds ?? ''} /></div><textarea className="control mt-2" onChange={(e) => setDraft({ ...draft, timeline: patchItem(draft.timeline, index, { description: e.target.value }) })} placeholder="Event description" value={item.description} /><RemoveButton onClick={() => setDraft({ ...draft, timeline: draft.timeline.filter((_, i) => i !== index) })} /></div>)}<AddButton onClick={() => setDraft({ ...draft, timeline: [...draft.timeline, { start_seconds: draft.incident.start_timestamp, end_seconds: null, description: '' }] })} /></div></label>
                  <label className="mt-3 block text-xs font-bold">Uncertainties<div className="mt-2 space-y-2">{draft.uncertainties.map((item, index) => <div className="flex gap-2" key={index}><input className="control" onChange={(e) => setDraft({ ...draft, uncertainties: draft.uncertainties.map((value, i) => i === index ? e.target.value : value) })} value={item} /><RemoveButton onClick={() => setDraft({ ...draft, uncertainties: draft.uncertainties.filter((_, i) => i !== index) })} /></div>)}<AddButton onClick={() => setDraft({ ...draft, uncertainties: [...draft.uncertainties, ''] })} /></div></label>
                  <div className="mt-4 flex flex-wrap items-center gap-2"><button className="rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={editBusy || !draft.incident.description.trim()} onClick={() => void saveReport()} type="button">{editBusy ? 'Saving…' : 'Save edited report'}</button><button className="action" disabled={editBusy} onClick={() => { setDraft(currentReport); setEditMessage(''); setEditingSummary(false); }} type="button">Cancel</button></div>
                  {editMessage && <p aria-live="polite" className="mt-3 text-xs text-ink/55">{editMessage}</p>}
                </div>
              </div>
            ) : <p className="mt-3 whitespace-pre-wrap text-base leading-7 text-ink/75">{incident.description}</p>}
          </section>
          <section className="mt-7 rounded-2xl bg-canvas p-5">
            <h3 className="font-semibold">Why severity {incident.severity_level}</h3>
            <p className="mt-2 text-sm leading-6 text-ink/60">{incident.severity_reason || 'No severity rationale was recorded.'}</p>
          </section>

          <div className="mt-7 grid gap-5 sm:grid-cols-2">
            <EvidenceGroup title="People and entities" empty="None identified" items={currentReport.entities.map((item) => `${item.entity_id} (${item.type}): ${item.description}`)} />
            <EvidenceGroup title="Instruments" empty="None identified" items={currentReport.instruments.map((item) => `${item.instrument_id} ${item.name} (threat ${item.threat_level}/5${item.entity_id ? `, held by ${item.entity_id}` : ''}): ${item.description}`)} />
            <EvidenceGroup title="Assets" empty="None identified" items={currentReport.assets.map((item) => `${item.asset_id} ${item.name}: ${item.description}`)} />
            <EvidenceGroup title="Uncertainties" empty="No material uncertainty reported" items={currentReport.uncertainties} />
          </div>
        </div>
      </div>

      <section className="border-t border-ink/10 px-6 py-6 sm:px-8">
        <h3 className="text-sm font-bold uppercase tracking-[0.12em] text-ink/45">Written report</h3>
        {report.reportText
          ? <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-ink/70">{report.reportText}</p>
          : <p className="mt-3 text-sm italic text-ink/45">{report.reportTextError ? `The written report could not be generated: ${report.reportTextError}` : 'No written report was generated for this run.'}</p>}
      </section>

      <section className="border-t border-ink/10 px-6 py-6 sm:px-8">
        <details className="group rounded-2xl border border-ink/10 bg-canvas/60">
          <summary className="cursor-pointer list-none px-5 py-4 text-sm font-semibold focus:outline-none focus:ring-2 focus:ring-inset focus:ring-signal">
            <span className="flex items-center justify-between"><span>Analysis provenance and diagnostics</span><span className="text-ink/35 group-open:rotate-180">⌄</span></span>
          </summary>
          <div className="border-t border-ink/10 px-5 py-5">
            <dl className="grid gap-x-6 gap-y-4 text-xs sm:grid-cols-2 lg:grid-cols-4">
              <Provenance label="Model" value={report.model} />
              <Provenance label="Contract / prompt version" value={report.promptVersion || 'Legacy prompt'} />
              <Provenance label="Model run" value={report.modelRunId} />
              <Provenance label="Generated" value={new Date(report.generatedAt).toLocaleString()} />
            </dl>
            {report.rawModelOutput ? (
              <div className="mt-6">
                <h4 className="text-xs font-bold uppercase tracking-[0.12em] text-ink/45">Raw model output</h4>
                <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-xl bg-ink p-4 font-mono text-xs leading-5 text-white/75">{report.rawModelOutput}</pre>
              </div>
            ) : <p className="mt-6 text-xs italic text-ink/40">Raw output was not retained for this model run.</p>}
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
  const { incident } = report;
  return <div className="mt-3 max-h-[70vh] space-y-4 overflow-auto pr-1 text-sm leading-6 text-ink/65">
    <div><strong>Title:</strong> {incident.title || '—'}<br /><strong>Incident type:</strong> {incident.type}<br /><strong>Location:</strong> {incident.location || '—'}<br /><strong>Severity:</strong> {incident.severity_level}/5 · <strong>Confidence:</strong> {confidenceLabel(incident.confidence_score)}<br /><strong>Time:</strong> {secondsLabel(incident.start_timestamp)}–{secondsLabel(incident.end_timestamp)} · {incident.duration} seconds</div>
    <div><strong>Executive summary</strong><p className="whitespace-pre-wrap">{incident.description || '—'}</p></div>
    <div><strong>Severity reason</strong><p className="whitespace-pre-wrap">{incident.severity_reason || '—'}</p></div>
    <div><strong>People and entities</strong>{report.entities.length ? report.entities.map((item) => <p key={item.entity_id}>{item.entity_id} ({item.type}): {item.description}</p>) : <p>None identified</p>}</div>
    <div><strong>Instruments</strong>{report.instruments.length ? report.instruments.map((item) => <p key={item.instrument_id}>{item.instrument_id} {item.name}: {item.description} (threat {item.threat_level}/5{item.entity_id ? `, held by ${item.entity_id}` : ''})</p>) : <p>None identified</p>}</div>
    <div><strong>Assets</strong>{report.assets.length ? report.assets.map((item) => <p key={item.asset_id}>{item.asset_id} {item.name}: {item.description}</p>) : <p>None identified</p>}</div>
    <div><strong>Timeline</strong>{report.timeline.length ? report.timeline.map((item, index) => <p key={index}>{secondsLabel(item.start_seconds)}{item.end_seconds === null ? '' : `–${secondsLabel(item.end_seconds)}`} · {item.description}</p>) : <p>No timestamped events</p>}</div>
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
