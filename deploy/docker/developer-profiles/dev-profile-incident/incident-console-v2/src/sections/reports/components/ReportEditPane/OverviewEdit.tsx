// SPDX-License-Identifier: Apache-2.0

'use client';

import type { ReactNode } from 'react';

import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Textarea } from '@/components/ui/textarea';
import { severityStyle } from '@/lib/ui/severity';
import { cn } from '@/lib/utils';
import { EDITABLE_INCIDENT_TYPES } from '@/modules/reports/domain/edit-draft';
import type { Overview } from '@/modules/reports/domain/envelope';
import type { OverviewDraft } from '@/modules/reports/domain/overview-draft';

const capitalize = (value: string | null) => (value ? value[0].toUpperCase() + value.slice(1) : 'Not set');
const NONE = '__none__';

/**
 * The overview side of edit mode: the version the draft started from (A, read-only) beside the editable draft (B),
 * field by field. Saving it replaces only the overview; every camera's report is kept as it was.
 */
export function OverviewEdit({ a, draft, onChange }: { a: Overview; draft: OverviewDraft; onChange: (draft: OverviewDraft) => void }) {
  const patch = (next: Partial<OverviewDraft>) => onChange({ ...draft, ...next });
  return (
    <section className="mt-5" data-testid="overview-fields-compare">
      <h3 className="font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-ink-caption">Overview fields</h3>
      <dl className="m-0">
        <Field
          label="Title"
          left={a.title ?? 'Not set'}
          right={
            <Input
              aria-label="Draft overview title"
              className="h-9 text-xs"
              onChange={(event) => patch({ title: event.target.value })}
              value={draft.title ?? ''}
            />
          }
        />
        <Field
          label="Incident type"
          left={capitalize(a.type)}
          right={
            <Select onValueChange={(val) => patch({ type: val === NONE ? null : val })} value={draft.type ?? NONE}>
              <SelectTrigger aria-label="Draft overview type" className="h-9 w-full bg-white text-xs">
                <SelectValue placeholder="Choose…" />
              </SelectTrigger>
              <SelectContent position="popper">
                <SelectItem value={NONE}>Choose…</SelectItem>
                {EDITABLE_INCIDENT_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {capitalize(type)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          }
        />
        <Field
          label="Severity"
          left={
            <span className={`rounded-full px-3 py-0.5 text-xs font-bold ${severityStyle(a.severity_level)}`}>
              {a.severity_level ?? '—'}/5
            </span>
          }
          right={
            <Select
              onValueChange={(val) => patch({ severity_level: val === NONE ? null : Number(val) })}
              value={draft.severity_level ? String(draft.severity_level) : NONE}
            >
              <SelectTrigger
                aria-label="Draft overview severity"
                className={cn('h-9 w-full bg-white text-xs font-bold', severityStyle(draft.severity_level))}
              >
                <SelectValue placeholder="Choose…" />
              </SelectTrigger>
              <SelectContent position="popper">
                <SelectItem value={NONE}>Choose…</SelectItem>
                {[1, 2, 3, 4, 5].map((level) => (
                  <SelectItem key={level} value={String(level)}>
                    {level}/5
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          }
        />
        <Field
          label="Location"
          left={a.location ?? 'Not set'}
          right={
            <Input
              aria-label="Draft overview location"
              className="h-9 text-xs"
              onChange={(event) => patch({ location: event.target.value })}
              value={draft.location ?? ''}
            />
          }
        />
        <Field
          label="Summary"
          left={<span className="whitespace-pre-wrap">{a.description ?? 'No summary was recorded.'}</span>}
          right={
            <Textarea
              aria-label="Draft overview summary"
              className="min-h-[92px] text-xs"
              onChange={(event) => patch({ description: event.target.value })}
              value={draft.description ?? ''}
            />
          }
        />
      </dl>
    </section>
  );
}

function Field({ label, left, right }: { label: string; left: ReactNode; right: ReactNode }) {
  return (
    <div className="grid gap-1.5 border-b border-ink/10 py-3 sm:grid-cols-[6rem_minmax(0,1fr)_minmax(0,1fr)] sm:gap-4">
      <dt className="pt-0.5 font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-ink-caption">{label}</dt>
      <dd className="m-0 min-w-0 text-sm leading-6 text-ink/80">{left}</dd>
      <dd className="m-0 min-w-0 text-sm leading-6 text-ink/80">{right}</dd>
    </div>
  );
}
