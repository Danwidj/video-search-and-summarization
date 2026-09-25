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

export function IncidentReport({ report, onNewAnalysis }: { report: AnalysisReport; onNewAnalysis: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [copied, setCopied] = useState(false);
  const [reviewStatus, setReviewStatus] = useState(report.reviewStatus || 'unreviewed');
  const [reviewBusy, setReviewBusy] = useState(false);

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
            <h2 className="mt-3 text-3xl font-semibold tracking-[-0.035em] sm:text-4xl">{report.title || 'Incident Report'}</h2>
            <p className="mt-3 text-sm text-ink/55">
              {report.incident_type}{report.location ? ` · ${report.location}` : ''} · {report.filename}
            </p>
          </div>
          <div className="flex shrink-0 gap-2">
            <span className={`rounded-full px-4 py-2 text-sm font-bold ${severityStyle(report.severity)}`}>Severity {report.severity}/5</span>
            <span className="rounded-full bg-white px-4 py-2 text-sm font-semibold text-ink/65">{Math.round(report.confidence * 100)}% confidence</span>
          </div>
        </div>
      </header>

      <section className="print-hidden flex flex-col gap-3 border-b border-ink/10 bg-white px-6 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <div><p className="text-xs font-bold uppercase tracking-[0.12em] text-ink/40">Human review</p><p className="mt-1 text-sm text-ink/60">Current status: <strong className="text-ink">{reviewStatus === 'under review' ? 'Under review' : reviewStatus[0].toUpperCase() + reviewStatus.slice(1)}</strong></p></div>
        <div className="flex flex-wrap gap-2">
          {reviewStatus !== 'under review' && <button className="action" disabled={reviewBusy} onClick={() => void changeReviewStatus('under review')} type="button">Start review</button>}
          {reviewStatus !== 'verified' && <button className="rounded-full bg-moss px-4 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={reviewBusy} onClick={() => void changeReviewStatus('verified')} type="button">Verify report</button>}
          {reviewStatus !== 'unreviewed' && <button className="action" disabled={reviewBusy} onClick={() => void changeReviewStatus('unreviewed')} type="button">Reset review</button>}
        </div>
      </section>

      <div className="grid lg:grid-cols-[1.08fr_0.92fr]">
        <div className="border-b border-ink/10 p-5 lg:border-b-0 lg:border-r sm:p-7">
          <video className="aspect-video w-full rounded-2xl bg-black object-contain" controls ref={videoRef} src={report.playbackUrl} />
          <div className="mt-6">
            <h3 className="text-sm font-bold uppercase tracking-[0.12em] text-ink/45">Event timeline</h3>
            {report.timeline.length ? <ol className="mt-3 space-y-2">
              {report.timeline.map((event, index) => (
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
            <p className="mt-3 text-base leading-7 text-ink/75">{report.description}</p>
          </section>
          <section className="mt-7 rounded-2xl bg-canvas p-5">
            <h3 className="font-semibold">Why severity {report.severity}</h3>
            <p className="mt-2 text-sm leading-6 text-ink/60">{report.severity_reason}</p>
          </section>

          <div className="mt-7 grid gap-5 sm:grid-cols-2">
            <EvidenceGroup
              title="People and entities"
              empty="None identified"
              items={report.persons.map((item) => [item.description, item.actions].filter(Boolean).join(': ') || item.description || 'Person')}
            />
            <EvidenceGroup
              title="Instruments"
              empty="None identified"
              items={report.instruments.map((item) => `${item.name}${item.threat_level ? ` (threat: ${item.threat_level}/5)` : ''}: ${item.description}`)}
            />
            <EvidenceGroup
              title="Assets"
              empty="None identified"
              items={report.assets.map((item) => `${item.name}: ${item.description}`)}
            />
            <EvidenceGroup
              title="Uncertainties"
              empty="No material uncertainty reported"
              items={report.uncertainties}
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
