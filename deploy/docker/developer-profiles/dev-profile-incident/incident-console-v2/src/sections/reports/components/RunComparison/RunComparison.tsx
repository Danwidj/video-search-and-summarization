// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { formatTimestamp } from '@/lib/time';
import { formatClock } from '@/modules/reports/domain/normalize';
import { reportHeading, type ReportView } from '@/modules/reports/domain/report-view';
import type { RevisionSummary } from '@/modules/reports/domain/revision';

const versionLabel = (revision: RevisionSummary) =>
  `v${revision.revisionNo} · ${revision.kind === 'human' ? 'Human' : 'AI'}${revision.isOfficial ? ' · ★ official' : ''}`;

export function RunComparison({ videoId, left, right }: { videoId: string; left: string; right: string }) {
  const router = useRouter();
  const [reports, setReports] = useState<Array<ReportView | null>>([null, null]);
  const [error, setError] = useState('');
  const [revisions, setRevisions] = useState<RevisionSummary[] | null>(null);
  const hasBoth = left !== '' && right !== '';

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/reports/${encodeURIComponent(videoId)}/revisions`, { cache: 'no-store', signal: controller.signal })
      .then((response) => (response.ok ? (response.json() as Promise<{ revisions?: RevisionSummary[] }>) : { revisions: undefined }))
      .then((payload) => setRevisions(payload.revisions ?? []))
      .catch((cause: unknown) => {
        if (!(cause instanceof DOMException && cause.name === 'AbortError')) setRevisions([]);
      });
    return () => controller.abort();
  }, [videoId]);

  useEffect(() => {
    setReports([null, null]);
    setError('');
    // Without both versions there is nothing to fetch; the picker below asks for them.
    if (!hasBoth) return;
    const controller = new AbortController();
    Promise.all(
      [left, right].map((revision) =>
        fetch(`/api/reports/${encodeURIComponent(videoId)}?revision=${encodeURIComponent(revision)}`, { signal: controller.signal }).then(
          (response) => {
            if (!response.ok) throw new Error('Could not load a selected version');
            return response.json() as Promise<{ report: ReportView }>;
          },
        ),
      ),
    )
      .then((values) => setReports(values.map((value) => value.report)))
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === 'AbortError') return;
        setError(cause instanceof Error ? cause.message : 'Could not load a selected version');
      });
    return () => controller.abort();
  }, [videoId, left, right, hasBoth]);

  const pick = (side: 'left' | 'right', value: string) => {
    const next = { left, right, [side]: value };
    const params = new URLSearchParams();
    if (next.left) params.set('left', next.left);
    if (next.right) params.set('right', next.right);
    router.replace(`/reports/${encodeURIComponent(videoId)}/compare?${params.toString()}`);
  };

  return (
    <div className="mx-auto max-w-[1500px] px-6 pb-20 pt-8 lg:px-12">
      <Button asChild className="-ml-2.5 text-moss hover:text-moss/80" size="sm" variant="ghost">
        <Link href={`/reports/${encodeURIComponent(videoId)}${left ? `?revision=${encodeURIComponent(left)}` : ''}`}>← Back to report</Link>
      </Button>
      <h1 className="mt-5 text-4xl font-semibold">Version comparison</h1>
      <div className="mt-5 grid max-w-2xl gap-3 sm:grid-cols-2" data-testid="compare-pickers">
        <VersionPicker label="Version A" onChange={(value) => pick('left', value)} revisions={revisions} taken={right} value={left} />
        <VersionPicker label="Version B" onChange={(value) => pick('right', value)} revisions={revisions} taken={left} value={right} />
      </div>
      {!hasBoth && (
        <Card className="mt-8 rounded-3xl border border-ink/10 bg-white p-6" data-testid="compare-empty">
          <h2 className="text-lg font-semibold">Choose two versions to compare</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {revisions !== null && revisions.length < 2
              ? 'This video has only one version, so there is nothing to compare yet.'
              : 'Pick a Version A and a Version B above to see them side by side.'}
          </p>
        </Card>
      )}
      {error && (
        <Alert className="mt-5" variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {hasBoth && !error && (
        <div className="mt-8 grid gap-5 lg:grid-cols-2">
          {reports.map((report, index) =>
            report ? (
              <RunCard index={index} key={report.revisionId} report={report} />
            ) : (
              <Card className="space-y-4 rounded-3xl border border-ink/10 bg-white p-6" key={index === 0 ? 'loading-a' : 'loading-b'}>
                <div className="flex items-center justify-between">
                  <Skeleton className="h-4 w-32" />
                  <Skeleton className="h-5 w-20 rounded-full" />
                </div>
                <Skeleton className="h-8 w-2/3" />
                <Skeleton className="h-3 w-40" />
                <div className="grid grid-cols-2 gap-3 pt-2">
                  <Skeleton className="h-14 rounded-xl" />
                  <Skeleton className="h-14 rounded-xl" />
                  <Skeleton className="h-14 rounded-xl" />
                  <Skeleton className="h-14 rounded-xl" />
                </div>
                <Skeleton className="h-20 rounded-xl" />
              </Card>
            ),
          )}
        </div>
      )}
    </div>
  );
}

function VersionPicker({
  label,
  value,
  taken,
  revisions,
  onChange,
}: {
  label: string;
  value: string;
  /** The version already chosen on the other side: comparing a version with itself shows nothing. */
  taken: string;
  revisions: RevisionSummary[] | null;
  onChange: (value: string) => void;
}) {
  const id = `compare-${label.replace(/\s/g, '-').toLowerCase()}`;
  return (
    <div className="space-y-1.5">
      <Label className="text-xs font-bold" htmlFor={id}>
        {label}
      </Label>
      <Select disabled={revisions === null} onValueChange={onChange} value={value}>
        <SelectTrigger className="w-full bg-white" id={id}>
          <SelectValue placeholder={revisions === null ? 'Loading versions…' : 'Choose a version'} />
        </SelectTrigger>
        <SelectContent position="popper">
          {(revisions ?? []).map((revision) => (
            <SelectItem disabled={String(revision.revisionId) === taken} key={revision.revisionId} value={String(revision.revisionId)}>
              {versionLabel(revision)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

function RunCard({ report, index }: { report: ReportView; index: number }) {
  const { incident, entities, instruments, assets } = report.structured;
  const model = report.modelOutput;
  return (
    <Card className="rounded-3xl border border-ink/10 bg-white p-6 shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Badge className="border-moss/20 font-mono text-xs uppercase tracking-wider text-moss" variant="outline">
          {index === 0 ? 'Version A' : 'Version B'}
        </Badge>
        <p className="font-mono text-xs text-ink-caption">
          v{report.revision.revisionNo} {report.revision.kind === 'human' ? `human (${report.revision.createdBy ?? 'unknown'})` : 'AI'} ·{' '}
          {formatTimestamp(report.revision.createdAt, '')}
        </p>
      </div>
      <h2 className="mt-3 text-2xl font-semibold">{reportHeading(report)}</h2>
      <p className="mt-1 text-xs text-ink-caption">
        {report.run.model} · {report.run.promptVersion || 'legacy prompt'}
      </p>
      <dl className="mt-5 grid grid-cols-2 gap-3">
        <Field label="Type" value={incident.type || 'Unclassified'} />
        <Field label="Severity" value={`${incident.severityLevel ?? '—'}/5`} />
        <Field
          label="Confidence"
          value={incident.confidenceScore === null ? 'Not provided' : `${Math.round(incident.confidenceScore * 100)}%`}
        />
        <Field
          label="Incident window"
          value={
            incident.startSeconds === null
              ? '—'
              : `${formatClock(incident.startSeconds)}–${incident.endSeconds === null ? '—' : formatClock(incident.endSeconds)}`
          }
        />
      </dl>
      <section className="mt-5">
        <h3 className="text-xs font-bold uppercase text-ink-caption">Summary</h3>
        <p className="mt-2 text-sm leading-6 text-ink/70">{incident.description}</p>
      </section>
      <section className="mt-5">
        <h3 className="text-xs font-bold uppercase text-ink-caption">Model severity rationale</h3>
        <p className="mt-2 text-sm leading-6 text-ink/70">{model?.severityReason ?? '—'}</p>
      </section>
      <section className="mt-5">
        <h3 className="text-xs font-bold uppercase text-ink-caption">Evidence</h3>
        <ul className="mt-2 space-y-1 text-sm text-ink/65">
          {[
            ...entities.map((x) => `${x.entityId} (${x.type}): ${x.description}`),
            ...instruments.map((x) => `${x.instrumentId} ${x.name}: ${x.description}${x.entityId ? ` · held by ${x.entityId}` : ''}`),
            ...assets.map((x) => `${x.assetId} ${x.name}: ${x.description}`),
          ].map((value) => (
            <li key={value}>• {value}</li>
          ))}
        </ul>
      </section>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-canvas p-3">
      <dt className="text-[10px] font-bold uppercase tracking-wider text-ink-caption">{label}</dt>
      <dd className="mt-1 text-sm font-semibold">{value}</dd>
    </div>
  );
}
