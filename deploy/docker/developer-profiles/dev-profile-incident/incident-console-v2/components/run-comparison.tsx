// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { formatClock } from '@/lib/reports/normalize';
import { reportHeading, type ReportView } from '@/lib/reports/report-view';

export function RunComparison({ videoId, left, right }: { videoId: string; left: string; right: string }) {
  const [reports, setReports] = useState<Array<ReportView | null>>([null, null]);
  const [error, setError] = useState('');
  useEffect(() => {
    Promise.all([left, right].map((run) => fetch(`/api/reports/${encodeURIComponent(videoId)}?run=${encodeURIComponent(run)}`).then((response) => {
      if (!response.ok) throw new Error('Could not load a selected run');
      return response.json() as Promise<{ report: ReportView }>;
    })))
      .then((values) => setReports(values.map((value) => value.report)))
      .catch((cause: Error) => setError(cause.message));
  }, [videoId, left, right]);

  return (
    <div className="mx-auto max-w-[1500px] px-6 pb-20 pt-8 lg:px-12">
      <Link className="text-sm font-semibold text-moss" href={`/reports/${videoId}?run=${encodeURIComponent(left)}`}>← Back to report</Link>
      <h1 className="mt-5 text-4xl font-semibold">Model-run comparison</h1>
      {error && <p className="mt-5 text-clay">{error}</p>}
      <div className="mt-8 grid gap-5 lg:grid-cols-2">
        {reports.map((report, index) => report ? <RunCard index={index} key={report.modelRunId} report={report} /> : <div className="animate-pulse rounded-3xl bg-white p-10" key={index}>Loading run…</div>)}
      </div>
    </div>
  );
}

function RunCard({ report, index }: { report: ReportView; index: number }) {
  const { incident, entities, instruments, assets } = report.structured;
  const model = report.modelOutput;
  return (
    <article className="rounded-3xl border border-ink/10 bg-white p-6">
      <p className="font-mono text-xs uppercase tracking-wider text-moss">{index === 0 ? 'Run A' : 'Run B'} · {report.run.generatedAt ? new Date(report.run.generatedAt).toLocaleString() : ''}</p>
      <h2 className="mt-3 text-2xl font-semibold">{reportHeading(report)}</h2>
      <p className="mt-1 text-xs text-ink/45">{report.run.model} · {report.run.promptVersion || 'legacy prompt'}</p>
      <dl className="mt-5 grid grid-cols-2 gap-3">
        <Field label="Type" value={incident.type || 'Unclassified'} />
        <Field label="Severity" value={`${incident.severityLevel ?? '—'}/5`} />
        <Field label="Confidence" value={incident.confidenceScore === null ? 'Not provided' : `${Math.round(incident.confidenceScore * 100)}%`} />
        <Field label="Incident window" value={incident.startSeconds === null ? '—' : `${formatClock(incident.startSeconds)}–${incident.endSeconds === null ? '—' : formatClock(incident.endSeconds)}`} />
      </dl>
      <section className="mt-5"><h3 className="text-xs font-bold uppercase text-ink/40">Summary</h3><p className="mt-2 text-sm leading-6 text-ink/70">{incident.description}</p></section>
      <section className="mt-5"><h3 className="text-xs font-bold uppercase text-ink/40">Model severity rationale</h3><p className="mt-2 text-sm leading-6 text-ink/70">{model?.severityReason ?? '—'}</p></section>
      <section className="mt-5">
        <h3 className="text-xs font-bold uppercase text-ink/40">Evidence</h3>
        <ul className="mt-2 space-y-1 text-sm text-ink/65">
          {[
            ...entities.map((x) => `${x.entityId} (${x.type}): ${x.description}`),
            ...instruments.map((x) => `${x.instrumentId} ${x.name}: ${x.description}${x.entityId ? ` · held by ${x.entityId}` : ''}`),
            ...assets.map((x) => `${x.assetId} ${x.name}: ${x.description}`),
          ].map((value, i) => <li key={i}>• {value}</li>)}
        </ul>
      </section>
      <section className="mt-5">
        <h3 className="text-xs font-bold uppercase text-ink/40">Model event timeline</h3>
        <ol className="mt-2 space-y-2 text-sm text-ink/65">{(model?.timeline ?? []).map((event, i) => <li key={i}><strong>{formatClock(event.startSeconds)}</strong> {event.description}</li>)}</ol>
      </section>
    </article>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl bg-canvas p-3"><dt className="text-[10px] font-bold uppercase tracking-wider text-ink/40">{label}</dt><dd className="mt-1 text-sm font-semibold">{value}</dd></div>;
}
