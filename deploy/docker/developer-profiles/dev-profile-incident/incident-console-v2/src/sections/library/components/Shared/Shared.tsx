// SPDX-License-Identifier: Apache-2.0
'use client';

import type * as React from 'react';
import { useState } from 'react';
import { cn } from 'cn';
import { AlertCircleIcon, XIcon } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { Select as ShadcnSelect, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { reportThumbnailView } from '@/lib/ui/thumbnail';
import { severityClass } from '@/lib/ui/severity';

export { severityClass };

export function SeverityChip({ level, className }: { level: number; className?: string }) {
  return (
    <Badge
      variant="outline"
      className={cn('h-auto rounded-full border px-2.5 py-0.5 text-[11px] font-bold leading-4', severityClass(level), className)}
    >
      Severity {level}
    </Badge>
  );
}

/** A small video screenshot (an evidence hit's incident), else a placeholder; a failed load is not retried. */
export function IncidentThumbnail({ url, className = 'aspect-video' }: { url?: string; className?: string }) {
  const [failed, setFailed] = useState(false);
  const view = reportThumbnailView(url, failed);
  return (
    <div aria-label="Video screenshot preview" className={cn('relative overflow-hidden bg-[#dfe3dc]', className)} role="img">
      {view.kind === 'image' ? (
        // biome-ignore lint/performance/noImgElement: a presigned R2 URL that next/image would proxy and re-encode through the console server
        <img alt="" className="h-full w-full object-cover" loading={view.loading} onError={() => setFailed(true)} src={view.src} />
      ) : (
        <div className="absolute inset-0 grid place-items-center bg-linear-to-br from-white/35 to-transparent">
          <div className="h-10 w-14 rounded-xl bg-white/55" />
        </div>
      )}
    </div>
  );
}

const EMPTY_SENTINEL = '__EMPTY_VALUE__';

export function Select({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
}) {
  const internalValue = value === '' ? EMPTY_SENTINEL : value;

  return (
    <ShadcnSelect
      value={internalValue}
      onValueChange={(val) => {
        onChange(val === EMPTY_SENTINEL ? '' : val);
      }}
    >
      <SelectTrigger aria-label={label} className="w-full bg-white shadow-xs">
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent position="popper" className="bg-white">
        {options.map(([key, text]) => (
          <SelectItem key={key || EMPTY_SENTINEL} value={key || EMPTY_SENTINEL}>
            {text}
          </SelectItem>
        ))}
      </SelectContent>
    </ShadcnSelect>
  );
}

export function FilterChip({ label, onRemove }: { label: React.ReactNode; onRemove: () => void }) {
  return (
    <Badge
      variant="secondary"
      className="inline-flex h-7 max-w-full items-center gap-1 rounded-full border border-ink/15 bg-white py-0 pl-2.5 pr-1 text-xs font-medium text-ink shadow-xs"
    >
      <span className="truncate">{label}</span>
      <button
        aria-label={`Remove filter ${typeof label === 'string' ? label : ''}`}
        className="grid size-4 shrink-0 place-items-center rounded-full hover:bg-ink/10 focus-visible:outline-none"
        onClick={onRemove}
        type="button"
      >
        <XIcon className="size-3" />
      </button>
    </Badge>
  );
}

export function CardSkeleton({ count = 6, label }: { count?: number; label: string }) {
  return (
    <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-3" role="status">
      <span className="sr-only">{label}</span>
      {Array.from({ length: count }, (_, i) => `skeleton-${label}-${i}`).map((key) => (
        <div className="flex flex-col overflow-hidden rounded-xl border border-ink/10 bg-white" key={key}>
          <Skeleton className="h-20 w-full rounded-none" />
          <div className="flex flex-1 flex-col gap-2.5 p-3.5">
            <Skeleton className="h-3 w-1/3" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-2/3" />
            <Skeleton className="mt-auto h-3 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ErrorPanel({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <Alert variant="destructive" className="mt-8 rounded-2xl border border-destructive/30 bg-white p-6 text-center">
      <div className="flex flex-col items-center gap-2">
        <AlertCircleIcon className="size-6 text-destructive" />
        <AlertTitle className="text-base font-semibold">Error</AlertTitle>
        <AlertDescription className="text-sm text-ink/70">{message}</AlertDescription>
        <Button variant="outline" className="mt-2 text-moss hover:text-moss/80" onClick={onRetry} type="button">
          Try again
        </Button>
      </div>
    </Alert>
  );
}
