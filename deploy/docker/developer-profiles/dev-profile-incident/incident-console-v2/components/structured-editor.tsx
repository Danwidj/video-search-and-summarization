// SPDX-License-Identifier: Apache-2.0

'use client';

import { useEffect, useMemo, useState } from 'react';

import {
  draftFromView,
  draftProblems,
  editFromDraft,
  type EditDraft,
} from '@/lib/reports/edit-draft';
import { formatClock } from '@/lib/reports/normalize';
import { PRESENTATION_REVIEWER } from '@/lib/presentation-reviewer';
import type { ReportView } from '@/lib/reports/report-view';

/**
 * Class A editor: incident type, window, summary, and severity level.
 * Entity, instrument, and asset fields are intentionally omitted from this
 * presentation branch.
 */
export function StructuredEditor({ report, onCancel, onSaved }: { report: ReportView; onCancel: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<EditDraft>(() => draftFromView(report));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string[]>([]);
  const [incidentTypes, setIncidentTypes] = useState<string[]>([]);
  const problems = useMemo(() => draftProblems(draft), [draft]);
  const legacy = report.run.notesKind !== 'contract';

  useEffect(() => {
    const controller = new AbortController();
    fetch('/api/reports?all=true', { cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        const payload = await response.json() as { reports?: Array<{ incident_type?: string }> };
        if (!response.ok || !Array.isArray(payload.reports)) return;
        const types = [...new Set(payload.reports.map((item) => item.incident_type?.trim().toLowerCase()).filter((type): type is string => Boolean(type)))].sort();
        setIncidentTypes(types);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  function setIncident(patch: Partial<EditDraft['incident']>) {
    setDraft((current) => ({ ...current, incident: { ...current.incident, ...patch } }));
  }

  async function save() {
    if (problems.length || busy) return;
    if (report.review.status === 'verified' && !window.confirm('This report is verified. Save a reviewer edit anyway?')) return;
    setBusy(true);
    setError([]);
    try {
      const response = await fetch(`/api/reports/${encodeURIComponent(report.videoId)}/edit`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modelRunId: report.modelRunId, editedBy: PRESENTATION_REVIEWER, edit: editFromDraft(draft) }),
      });
      const payload = (await response.json()) as { error?: string; violations?: Array<{ message: string }> };
      if (!response.ok) {
        setError(payload.violations?.length ? payload.violations.map((violation) => violation.message) : [payload.error || 'Save failed']);
        return;
      }
      onSaved();
    } catch (cause) {
      setError([cause instanceof Error ? cause.message : 'Save failed']);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 grid items-start gap-4 xl:grid-cols-2" data-testid="structured-editor">
      <OriginalModelOutput report={report} />
      <div className="rounded-2xl border border-moss/25 bg-white p-4 shadow-sm">
        <p className="text-xs font-bold uppercase tracking-[0.12em] text-moss">Reviewer edit · structured fields</p>
        <p className="mt-1 text-xs text-ink/50">
          Changes the report&apos;s structured values only. The model&apos;s original output, its title, severity rationale, timeline and uncertainties stay unchanged.
          {legacy ? ' Saving this earlier-format report stores its values in the current format (seconds, contract types, sequential IDs).' : ''}
        </p>

        <div className="mt-4 grid grid-cols-2 gap-2">
          <label className="text-xs font-bold">Incident type
            <select className="control mt-1" onChange={(e) => setIncident({ type: e.target.value || null })} value={draft.incident.type ?? ''}>
              <option value="">Choose…</option>
              {[...new Set([...(draft.incident.type ? [draft.incident.type] : []), ...incidentTypes])].map((type) => <option key={type} value={type}>{type}</option>)}
            </select>
          </label>
          <label className="text-xs font-bold">Severity level
            <select className="control mt-1" onChange={(e) => setIncident({ severity_level: e.target.value ? Number(e.target.value) : null })} value={draft.incident.severity_level ?? ''}>
              <option value="">Choose…</option>
              {[1, 2, 3, 4, 5].map((level) => <option key={level} value={level}>{level}/5</option>)}
            </select>
          </label>
          <SecondsInput label="Incident start (seconds)" onChange={(value) => setIncident({ start_timestamp: value })} value={draft.incident.start_timestamp} />
          <SecondsInput label="Incident end (seconds)" onChange={(value) => setIncident({ end_timestamp: value })} value={draft.incident.end_timestamp} />
        </div>
        <p className="mt-1 text-[11px] text-ink/45">
          Duration is calculated: {draft.incident.start_timestamp !== null && draft.incident.end_timestamp !== null && draft.incident.end_timestamp >= draft.incident.start_timestamp ? `${draft.incident.end_timestamp - draft.incident.start_timestamp} s` : '—'}
        </p>
        <label className="mt-3 block text-xs font-bold">Executive summary
          <textarea className="control mt-1 min-h-[100px]" onChange={(e) => setIncident({ description: e.target.value })} value={draft.incident.description} />
        </label>

        {problems.length > 0 && <ul className="mt-4 list-disc pl-5 text-xs text-clay">{problems.map((problem) => <li key={problem}>{problem}</li>)}</ul>}
        {error.length > 0 && <ul aria-live="polite" className="mt-4 list-disc pl-5 text-xs text-clay">{error.map((message, index) => <li key={index}>{message}</li>)}</ul>}
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button className="rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={busy || problems.length > 0} onClick={() => void save()} type="button">{busy ? 'Saving…' : 'Save reviewer edit'}</button>
          <button className="action" disabled={busy} onClick={onCancel} type="button">Cancel</button>
        </div>
      </div>
    </div>
  );
}

function SecondsInput({ label, value, onChange }: { label: string; value: number | null; onChange: (value: number | null) => void }) {
  return (
    <label className="text-xs font-bold">{label}
      <input className="control mt-1" inputMode="numeric" min={0} onChange={(e) => onChange(e.target.value === '' ? null : Math.max(0, Math.floor(Number(e.target.value))))} step={1} type="number" value={value ?? ''} />
      <span className="mt-0.5 block font-normal text-ink/45">{value === null ? 'not set' : formatClock(value)}</span>
    </label>
  );
}

function OriginalModelOutput({ report }: { report: ReportView }) {
  const model = report.modelOutput;
  return (
    <div className="rounded-2xl border border-ink/10 bg-canvas/60 p-4" data-testid="original-model-output">
      <p className="text-xs font-bold uppercase tracking-[0.12em] text-ink/40">Original model output · read-only</p>
      {!model ? <p className="mt-3 text-sm italic text-ink/45">The original model output was not retained for this run.</p> : (
        <div className="mt-3 max-h-[70vh] space-y-3 overflow-auto pr-1 text-sm leading-6 text-ink/65">
          <p><strong>Title:</strong> {model.title ?? '—'}</p>
          <p><strong>Type:</strong> {model.original.type ?? '—'} · <strong>Severity:</strong> {model.original.severityLevel ?? '—'}/5</p>
          <p><strong>Window:</strong> {model.original.startSeconds === null ? '—' : formatClock(model.original.startSeconds)}–{model.original.endSeconds === null ? '—' : formatClock(model.original.endSeconds)}</p>
          <div><strong>Summary</strong><p className="whitespace-pre-wrap">{model.original.description ?? '—'}</p></div>
          <div><strong>Model severity rationale</strong><p className="whitespace-pre-wrap">{model.severityReason ?? '—'}</p></div>
          {model.location && <p><strong>Location:</strong> {model.location}</p>}
          <div><strong>Timeline</strong>{model.timeline.length ? model.timeline.map((event, i) => <p key={i}>{formatClock(event.startSeconds)}{event.endSeconds === null ? '' : `–${formatClock(event.endSeconds)}`} · {event.description}</p>) : <p>No timestamped events</p>}</div>
          <div><strong>Uncertainties</strong>{model.uncertainties.length ? model.uncertainties.map((item, i) => <p key={i}>{item}</p>) : <p>None reported</p>}</div>
        </div>
      )}
    </div>
  );
}
