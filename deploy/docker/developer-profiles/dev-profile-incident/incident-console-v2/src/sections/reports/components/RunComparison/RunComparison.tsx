// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { formatTimestamp } from '@/lib/time';
import { formatClock } from '@/modules/reports/domain/normalize';
import { reportHeading, type ReportView } from '@/modules/reports/domain/report-view';

export function RunComparison({ videoId, left, right }: { videoId: string; left: string; right: string }) {
  const [reports, setReports] = useState<Array<ReportView | null>>([null, null]);
  const [error, setError] = useState('');
  useEffect(() => {
    Promise.all(
      [left, right].map((revision) =>
        fetch(`/api/reports/${encodeURIComponent(videoId)}?revision=${encodeURIComponent(revision)}`).then((response) => {
          if (!response.ok) throw new Error('Could not load a selected version');
          return response.json() as Promise<{ report: ReportView }>;
        }),
      ),
    )
      .then((values) => setReports(values.map((value) => value.report)))
      .catch((cause: Error) => setError(cause.message));
  }, [videoId, left, right]);

  return (
    <div className="mx-auto max-w-[1500px] px-6 pb-20 pt-8 lg:px-12">
      <Button asChild className="-ml-2.5 text-moss hover:text-moss/80" size="sm" variant="ghost">
        <Link href={`/reports/${videoId}?revision=${encodeURIComponent(left)}`}>← Back to report</Link>
      </Button>
      <h1 className="mt-5 text-4xl font-semibold">Version comparison</h1>
      {error && (
        <Alert className="mt-5" variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <div className="mt-8 grid gap-5 lg:grid-cols-2">
        {reports.map((report, index) =>
          report ? (
            <RunCard index={index} key={report.revisionId} report={report} />
          ) : (
            <Card
              className="space-y-4 rounded-3xl border border-ink/10 bg-white p-6"
              key={index === 0 ? `loading-${left}` : `loading-${right}`}
            >
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
      <section className="mt-5">
        <h3 className="text-xs font-bold uppercase text-ink-caption">Model event timeline</h3>
        <ol className="mt-2 space-y-2 text-sm text-ink/65">
          {(model?.timeline ?? []).map((event) => (
            <li key={`${event.startSeconds}-${event.endSeconds ?? ''}-${event.description}`}>
              <strong className="text-ink">{formatClock(event.startSeconds)}</strong> {event.description}
            </li>
          ))}
        </ol>
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
