// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { useRunHistory } from '@/components/run-history';
import { EDITABLE_INCIDENT_TYPES } from '@/lib/reports/edit-draft';
import { formatClock, parseTimestamp } from '@/lib/reports/normalize';
import type { ReportView } from '@/lib/reports/report-view';
import { formatTimestamp } from '@/lib/time';
import { PRESENTATION_REVIEWER } from '@/lib/presentation-reviewer';

interface GroundTruthForm { type: string; description: string; start: string; end: string; severityLevel: string }

const EMPTY: GroundTruthForm = { type: '', description: '', start: '', end: '', severityLevel: '' };

/**
 * Human ground truth for a video, kept apart from model output. The form is
 * never pre-filled from a model's answer. A run can be chosen for a read-only
 * side-by-side; automatic scoring stays in eval/.
 */
export function GroundTruthScreen({ videoId, runId }: { videoId: string; runId?: string }) {
  const { history } = useRunHistory(videoId);
  const [form, setForm] = useState<GroundTruthForm>(EMPTY);
  const [labelled, setLabelled] = useState<{ by?: string; at?: string } | null>(null);
  const [comparison, setComparison] = useState<ReportView | null>(null);
  const [selectedRun, setSelectedRun] = useState(runId || '');
  const [message, setMessage] = useState('');

  useEffect(() => {
    void fetch(`/api/reports/${encodeURIComponent(videoId)}/ground-truth`, { cache: 'no-store' })
      .then((response) => response.json() as Promise<{ groundTruth?: Record<string, unknown> | null }>)
      .then(({ groundTruth }) => {
        if (!groundTruth) return;
        const type = String(groundTruth.type ?? '').trim().toLowerCase();
        const start = parseTimestamp(groundTruth.start_timestamp);
        const end = parseTimestamp(groundTruth.end_timestamp);
        setForm({
          type: (EDITABLE_INCIDENT_TYPES as readonly string[]).includes(type) ? type : '',
          description: String(groundTruth.description ?? ''),
          start: start === null ? '' : String(start),
          end: end === null ? '' : String(end),
          severityLevel: typeof groundTruth.severity_level === 'number' ? String(groundTruth.severity_level) : '',
        });
        setLabelled({ by: typeof groundTruth.labelled_by === 'string' ? groundTruth.labelled_by : undefined, at: typeof groundTruth.labelled_datetime === 'string' ? groundTruth.labelled_datetime : undefined });
      })
      .catch(() => undefined);
  }, [videoId]);

  useEffect(() => {
    if (!selectedRun) { setComparison(null); return; }
    void fetch(`/api/reports/${encodeURIComponent(videoId)}?run=${encodeURIComponent(selectedRun)}`, { cache: 'no-store' })
      .then((response) => (response.ok ? response.json() as Promise<{ report: ReportView }> : null))
      .then((payload) => setComparison(payload?.report ?? null))
      .catch(() => setComparison(null));
  }, [selectedRun, videoId]);

  const reportRuns = (history?.runs || []).filter((run) => run.report);
  const start = form.start === '' ? null : Number(form.start);
  const end = form.end === '' ? null : Number(form.end);
  const problems = [
    !form.type && 'Choose an incident type.',
    (start === null || end === null || !Number.isInteger(start) || !Number.isInteger(end) || start < 0) && 'Enter start and end as whole seconds.',
    start !== null && end !== null && end < start && 'The end must not be before the start.',
    !form.severityLevel && 'Choose a severity level.',
    !selectedRun && 'Choose the analysis this ground truth is compared with (recorded in the severity evaluation log).',
  ].filter(Boolean) as string[];

  async function save() {
    if (problems.length) return;
    const labelledBy = PRESENTATION_REVIEWER;
    const response = await fetch(`/api/reports/${encodeURIComponent(videoId)}/ground-truth`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ modelRunId: selectedRun, type: form.type, description: form.description, startTimestamp: String(start), endTimestamp: String(end), duration: end! - start!, severityLevel: Number(form.severityLevel), labelledBy }),
    });
    const payload = (await response.json()) as { error?: string };
    setMessage(response.ok ? 'Ground truth saved.' : payload.error || 'Save failed');
    if (response.ok) setLabelled({ by: labelledBy, at: new Date().toISOString() });
  }

  return (
    <div className="mx-auto grid max-w-[1500px] gap-6 px-4 pb-16 pt-6 sm:px-6 lg:grid-cols-2 lg:px-12">
      <section className="rounded-3xl border border-ink/10 bg-white p-6" data-testid="ground-truth-form">
        <p className="font-mono text-xs uppercase tracking-[.15em] text-moss">Human ground truth</p>
        <h1 className="mt-2 text-xl font-semibold">Label this video</h1>
        <p className="mt-1 text-xs text-ink/50">Entered by a person from the video itself; never pre-filled from a model&apos;s answer.{labelled?.by ? ` Last labelled by ${labelled.by}${labelled.at ? ` on ${formatTimestamp(labelled.at)}` : ''}.` : ''}</p>
        <label className="mt-4 block text-xs font-bold">Incident type
          <select className="control mt-1" onChange={(e) => setForm({ ...form, type: e.target.value })} value={form.type}>
            <option value="">Choose…</option>
            {EDITABLE_INCIDENT_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
          </select>
        </label>
        <label className="mt-3 block text-xs font-bold">Description
          <textarea className="control mt-1 min-h-[90px]" onChange={(e) => setForm({ ...form, description: e.target.value })} value={form.description} />
        </label>
        <div className="mt-3 grid grid-cols-3 gap-2">
          <label className="text-xs font-bold">Start (s)<input className="control mt-1" min={0} onChange={(e) => setForm({ ...form, start: e.target.value })} step={1} type="number" value={form.start} /></label>
          <label className="text-xs font-bold">End (s)<input className="control mt-1" min={0} onChange={(e) => setForm({ ...form, end: e.target.value })} step={1} type="number" value={form.end} /></label>
          <label className="text-xs font-bold">Severity
            <select className="control mt-1" onChange={(e) => setForm({ ...form, severityLevel: e.target.value })} value={form.severityLevel}>
              <option value="">…</option>{[1, 2, 3, 4, 5].map((level) => <option key={level} value={level}>{level}/5</option>)}
            </select>
          </label>
        </div>
        {problems.length > 0 && <ul className="mt-3 list-disc pl-5 text-xs text-clay">{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>}
        <button className="mt-4 rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={problems.length > 0} onClick={() => void save()} type="button">Save ground truth</button>
        {message && <p className="mt-2 text-xs text-ink/60">{message}</p>}
      </section>
      <section className="rounded-3xl border border-ink/10 bg-white p-6" data-testid="ground-truth-comparison">
        <p className="font-mono text-xs uppercase tracking-[.15em] text-moss">Compare with an analysis</p>
        <label className="mt-3 block text-xs font-bold">Analysis
          <select className="control mt-1" onChange={(e) => setSelectedRun(e.target.value)} value={selectedRun}>
            <option value="">Choose an analysis with a report…</option>
            {reportRuns.map((run) => <option key={run.modelRunId} value={run.modelRunId}>{run.model} · {formatTimestamp(run.attemptedAt)}</option>)}
          </select>
        </label>
        {comparison && (
          <dl className="mt-4 grid grid-cols-3 gap-2 text-xs">
            <dt className="font-bold text-ink/40">Field</dt><dt className="font-bold text-ink/40">Ground truth</dt><dt className="font-bold text-ink/40">This analysis (current values)</dt>
            <Row label="Type" left={form.type || '—'} right={comparison.structured.incident.type ?? '—'} />
            <Row label="Window" left={start !== null && end !== null ? `${formatClock(start)}–${formatClock(end)}` : '—'} right={comparison.structured.incident.startSeconds !== null && comparison.structured.incident.endSeconds !== null ? `${formatClock(comparison.structured.incident.startSeconds)}–${formatClock(comparison.structured.incident.endSeconds)}` : '—'} />
            <Row label="Severity" left={form.severityLevel ? `${form.severityLevel}/5` : '—'} right={`${comparison.structured.incident.severityLevel ?? '—'}/5`} />
            <Row label="Description" left={form.description || '—'} right={comparison.structured.incident.description ?? '—'} />
          </dl>
        )}
        <p className="mt-4 text-[11px] text-ink/45">Read-only comparison. Automatic scoring against ground truth runs in the evaluation pipeline (eval/), not here.</p>
        <Link className="mt-3 inline-block text-xs font-semibold text-moss" href={`/videos/${encodeURIComponent(videoId)}`}>← Analysis history</Link>
      </section>
    </div>
  );
}

function Row({ label, left, right }: { label: string; left: string; right: string }) {
  return <><dd className="font-semibold text-ink/60">{label}</dd><dd className="text-ink/75">{left}</dd><dd className="text-ink/75">{right}</dd></>;
}
