// SPDX-License-Identifier: Apache-2.0

'use client';
import Link from 'next/link';
import { FormEvent, useEffect, useState } from 'react';

import { ReanalysisCard } from '@/components/reanalysis-card';
import { RunHistoryList, useRunHistory } from '@/components/run-history';
import { reportHeading, type ReportView } from '@/lib/reports/report-view';
import type { ReportLibraryItem } from '@/lib/reports/storage';

export function AdvancedReportTools({ report }: { report: ReportView }) {
  return (
    <>
      <section className="print-hidden mt-6 grid gap-6 xl:grid-cols-2">
        <FollowUpChat report={report} />
        <AnalysisHistoryCard report={report} />
      </section>
      <RunComparisonLauncher report={report} />
    </>
  );
}

function RunComparisonLauncher({ report }: { report: ReportView }) {
  const [other, setOther] = useState<ReportLibraryItem | null>(null);
  useEffect(() => { void fetch('/api/reports?all=true').then((r) => r.json()).then((p: { reports?: ReportLibraryItem[] }) => { setOther((p.reports || []).find((item) => item.videoId === report.videoId && item.modelRunId !== report.modelRunId) || null); }); }, [report]);
  if (!other) return null;
  return <div className="print-hidden mt-6 rounded-2xl border border-signal/25 bg-signal/5 p-5 text-sm"><strong>Another model run is available for this video.</strong><Link className="ml-3 font-bold text-moss" href={`/reports/${encodeURIComponent(report.videoId)}/compare?left=${encodeURIComponent(report.modelRunId)}&right=${encodeURIComponent(other.modelRunId)}`}>Compare runs side by side →</Link></div>;
}

function FollowUpChat({ report }: { report: ReportView }) {
  const [messages, setMessages] = useState<Array<{ role: 'user' | 'assistant'; content: string }>>([]); const [question, setQuestion] = useState(''); const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function ask(event: FormEvent) { event.preventDefault(); if (!question.trim() || busy) return; const next = [...messages, { role: 'user' as const, content: question.trim() }]; setMessages(next); setQuestion(''); setBusy(true); setError(''); try { const response = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ messages: next, reportContext: JSON.stringify(chatContext(report)) }) }); const payload = await response.json() as { content?: string; error?: string }; if (!response.ok || !payload.content) throw new Error(payload.error || 'No answer returned'); setMessages([...next, { role: 'assistant', content: payload.content }]); } catch (cause) { setError(cause instanceof Error ? cause.message : 'Chat failed'); } finally { setBusy(false); } }
  return <section className="flex min-h-[420px] flex-col rounded-3xl border border-ink/10 bg-white p-6"><p className="font-mono text-xs uppercase tracking-[.15em] text-moss">Report-grounded</p><h2 className="mt-2 text-xl font-semibold">Ask a follow-up</h2><div className="mt-4 flex-1 space-y-3 overflow-auto">{messages.length === 0 && <p className="text-sm leading-6 text-ink/45">Ask about timestamps, people, objects, evidence, or uncertainty. Answers use this stored report as context.</p>}{messages.map((m, i) => <div className={`rounded-2xl p-3 text-sm leading-6 ${m.role === 'user' ? 'ml-8 bg-ink text-white' : 'mr-8 bg-canvas text-ink/70'}`} key={i}>{m.content}</div>)}</div>{error && <p className="mt-2 text-xs text-clay">{error}</p>}<form className="mt-4 flex gap-2" onSubmit={ask}><input aria-label="Follow-up question" className="control" onChange={(e) => setQuestion(e.target.value)} placeholder="What happened before…?" value={question} /><button className="rounded-full bg-moss px-4 text-xs font-semibold text-white disabled:opacity-50" disabled={busy} type="submit">{busy ? 'Thinking…' : 'Ask'}</button></form></section>;
}

/** Re-analysis of this video plus its analysis history (replaces the former evaluation / ground-truth card). */
function AnalysisHistoryCard({ report }: { report: ReportView }) {
  const { history, error, reload } = useRunHistory(report.videoId);
  return (
    <section className="rounded-3xl border border-ink/10 bg-white p-6" data-testid="analysis-history-card">
      <p className="font-mono text-xs uppercase tracking-[.15em] text-moss">Analysis</p>
      <h2 className="mt-2 text-xl font-semibold">Analyse this video again</h2>
      <div className="mt-3"><ReanalysisCard onAttempted={() => void reload()} videoId={report.videoId} /></div>
      <div className="mt-6 border-t border-ink/10 pt-5">
        <p className="text-xs font-bold uppercase tracking-wider text-ink/40">Analysis history for this video</p>
        {error && <p className="mt-2 text-xs text-clay">{error}</p>}
        {history ? <div className="mt-2"><RunHistoryList compact currentRunId={report.modelRunId} history={history} /></div> : !error && <p className="mt-2 text-xs text-ink/45">Loading…</p>}
        <div className="mt-4 flex flex-wrap gap-4 text-xs font-semibold">
          <Link className="text-moss" href={`/videos/${encodeURIComponent(report.videoId)}`}>Full analysis history →</Link>
        </div>
      </div>
    </section>
  );
}

function chatContext(report: ReportView) {
  const { incident, entities, instruments, assets } = report.structured;
  return {
    title: reportHeading(report),
    incident: { type: incident.type, startSeconds: incident.startSeconds, endSeconds: incident.endSeconds, severityLevel: incident.severityLevel, description: incident.description },
    entities,
    instruments,
    assets,
    modelOutput: report.modelOutput && {
      severityRationale: report.modelOutput.severityReason,
      modelSeverityLevel: report.modelOutput.original.severityLevel,
      location: report.modelOutput.location,
      timeline: report.modelOutput.timeline,
      uncertainties: report.modelOutput.uncertainties,
    },
  };
}
