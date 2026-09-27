// SPDX-License-Identifier: Apache-2.0

'use client';

import { useMemo, useState, type ReactNode } from 'react';

import {
  EDITABLE_ENTITY_TYPES,
  EDITABLE_INCIDENT_TYPES,
  draftFromView,
  draftProblems,
  editFromDraft,
  newKey,
  type EditDraft,
} from '@/lib/reports/edit-draft';
import { formatClock } from '@/lib/reports/normalize';
import type { ReportView } from '@/lib/reports/report-view';

/**
 * Class A editor: incident type, window, summary, severity level, and the
 * entities / instruments / assets. Model-generated fields (title, severity
 * rationale, location, timeline, uncertainties) and provenance are shown
 * read-only on the left and are never part of an edit.
 */
export function StructuredEditor({ report, onCancel, onSaved }: { report: ReportView; onCancel: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<EditDraft>(() => draftFromView(report));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string[]>([]);
  const problems = useMemo(() => draftProblems(draft), [draft]);
  const legacy = report.run.notesKind !== 'contract';

  function setIncident(patch: Partial<EditDraft['incident']>) {
    setDraft((current) => ({ ...current, incident: { ...current.incident, ...patch } }));
  }

  async function save() {
    if (problems.length || busy) return;
    const editedBy = window.prompt('Your name is required to save a reviewer edit.');
    if (!editedBy?.trim()) return;
    if (report.review.status === 'verified' && !window.confirm('This report is verified. Save a reviewer edit anyway?')) return;
    setBusy(true);
    setError([]);
    try {
      const response = await fetch(`/api/reports/${encodeURIComponent(report.videoId)}/edit`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ modelRunId: report.modelRunId, editedBy: editedBy.trim(), edit: editFromDraft(draft) }),
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

  const entityOptions = draft.entities.map((entity, index) => ({ key: entity.key, label: `E${index + 1} (${entity.type})` }));

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
              {EDITABLE_INCIDENT_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
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

        <Section itemLabel="entity" title="Entities" onAdd={() => setDraft((d) => ({ ...d, entities: [...d.entities, { key: newKey('entity'), type: 'human', description: '' }] }))}>
          {draft.entities.map((entity, index) => (
            <div className="rounded-xl border border-ink/10 p-3" key={entity.key}>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-bold text-moss">E{index + 1}</span>
                <select aria-label={`Entity E${index + 1} type`} className="control" onChange={(e) => setDraft((d) => ({ ...d, entities: d.entities.map((x) => x.key === entity.key ? { ...x, type: e.target.value } : x) }))} value={entity.type}>
                  {EDITABLE_ENTITY_TYPES.map((type) => <option key={type} value={type}>{type}</option>)}
                </select>
                <Remove onClick={() => setDraft((d) => ({ ...d, entities: d.entities.filter((x) => x.key !== entity.key), instruments: d.instruments.map((i) => i.holderKey === entity.key ? { ...i, holderKey: null } : i) }))} />
              </div>
              <textarea aria-label={`Entity E${index + 1} description`} className="control mt-2" onChange={(e) => setDraft((d) => ({ ...d, entities: d.entities.map((x) => x.key === entity.key ? { ...x, description: e.target.value } : x) }))} value={entity.description} />
            </div>
          ))}
        </Section>

        <Section itemLabel="instrument" title="Instruments" onAdd={() => setDraft((d) => ({ ...d, instruments: [...d.instruments, { key: newKey('instrument'), holderKey: null, name: '', description: '', threat_level: null }] }))}>
          {draft.instruments.map((instrument, index) => (
            <div className="rounded-xl border border-ink/10 p-3" key={instrument.key}>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-bold text-moss">I{index + 1}</span>
                <input aria-label={`Instrument I${index + 1} name`} className="control" onChange={(e) => setDraft((d) => ({ ...d, instruments: d.instruments.map((x) => x.key === instrument.key ? { ...x, name: e.target.value } : x) }))} placeholder="Name" value={instrument.name} />
                <Remove onClick={() => setDraft((d) => ({ ...d, instruments: d.instruments.filter((x) => x.key !== instrument.key) }))} />
              </div>
              <textarea aria-label={`Instrument I${index + 1} description`} className="control mt-2" onChange={(e) => setDraft((d) => ({ ...d, instruments: d.instruments.map((x) => x.key === instrument.key ? { ...x, description: e.target.value } : x) }))} value={instrument.description} />
              <div className="mt-2 grid grid-cols-2 gap-2">
                <select aria-label={`Instrument I${index + 1} threat level`} className="control" onChange={(e) => setDraft((d) => ({ ...d, instruments: d.instruments.map((x) => x.key === instrument.key ? { ...x, threat_level: e.target.value ? Number(e.target.value) : null } : x) }))} value={instrument.threat_level ?? ''}>
                  <option value="">Threat level…</option>
                  {[1, 2, 3, 4, 5].map((level) => <option key={level} value={level}>threat {level}/5</option>)}
                </select>
                <select aria-label={`Instrument I${index + 1} held by`} className="control" onChange={(e) => setDraft((d) => ({ ...d, instruments: d.instruments.map((x) => x.key === instrument.key ? { ...x, holderKey: e.target.value || null } : x) }))} value={instrument.holderKey ?? ''}>
                  <option value="">Holder not determined</option>
                  {entityOptions.map((option) => <option key={option.key} value={option.key}>held by {option.label}</option>)}
                </select>
              </div>
            </div>
          ))}
        </Section>

        <Section itemLabel="asset" title="Assets" onAdd={() => setDraft((d) => ({ ...d, assets: [...d.assets, { key: newKey('asset'), name: '', description: '' }] }))}>
          {draft.assets.map((asset, index) => (
            <div className="rounded-xl border border-ink/10 p-3" key={asset.key}>
              <div className="flex items-center gap-2">
                <span className="font-mono text-xs font-bold text-moss">A{index + 1}</span>
                <input aria-label={`Asset A${index + 1} name`} className="control" onChange={(e) => setDraft((d) => ({ ...d, assets: d.assets.map((x) => x.key === asset.key ? { ...x, name: e.target.value } : x) }))} placeholder="Name" value={asset.name} />
                <Remove onClick={() => setDraft((d) => ({ ...d, assets: d.assets.filter((x) => x.key !== asset.key) }))} />
              </div>
              <textarea aria-label={`Asset A${index + 1} description`} className="control mt-2" onChange={(e) => setDraft((d) => ({ ...d, assets: d.assets.map((x) => x.key === asset.key ? { ...x, description: e.target.value } : x) }))} value={asset.description} />
            </div>
          ))}
        </Section>

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

function Section({ title, itemLabel, onAdd, children }: { title: string; itemLabel: string; onAdd: () => void; children: ReactNode }) {
  return (
    <div className="mt-4">
      <p className="text-xs font-bold">{title}</p>
      <div className="mt-2 space-y-2">{children}</div>
      <button className="mt-2 rounded-full border border-ink/15 px-3 py-1.5 text-xs font-semibold text-moss" onClick={onAdd} type="button">Add {itemLabel}</button>
    </div>
  );
}

function Remove({ onClick }: { onClick: () => void }) {
  return <button className="ml-auto rounded-full px-3 py-1.5 text-xs font-semibold text-clay" onClick={onClick} type="button">Remove</button>;
}

function OriginalModelOutput({ report }: { report: ReportView }) {
  const model = report.modelOutput;
  const original = report.run.originalReport as { entities?: Array<Record<string, unknown>>; instruments?: Array<Record<string, unknown>>; assets?: Array<Record<string, unknown>> } | undefined;
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
          {original?.entities && <div><strong>Entities</strong>{original.entities.map((e, i) => <p key={i}>{String(e.entity_id)} ({String(e.type)}): {String(e.description)}</p>)}</div>}
          {original?.instruments && <div><strong>Instruments</strong>{original.instruments.length ? original.instruments.map((x, i) => <p key={i}>{String(x.instrument_id)} {String(x.name)}: {String(x.description)} (threat {String(x.threat_level)}/5{x.entity_id ? `, held by ${String(x.entity_id)}` : ''})</p>) : <p>None</p>}</div>}
          {original?.assets && <div><strong>Assets</strong>{original.assets.length ? original.assets.map((a, i) => <p key={i}>{String(a.asset_id)} {String(a.name)}: {String(a.description)}</p>) : <p>None</p>}</div>}
          <div><strong>Timeline</strong>{model.timeline.length ? model.timeline.map((event, i) => <p key={i}>{formatClock(event.startSeconds)}{event.endSeconds === null ? '' : `–${formatClock(event.endSeconds)}`} · {event.description}</p>) : <p>No timestamped events</p>}</div>
          <div><strong>Uncertainties</strong>{model.uncertainties.length ? model.uncertainties.map((item, i) => <p key={i}>{item}</p>) : <p>None reported</p>}</div>
        </div>
      )}
    </div>
  );
}
