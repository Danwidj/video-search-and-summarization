// SPDX-License-Identifier: Apache-2.0
'use client';

import { useState } from 'react';

import { reportThumbnailView } from '@/lib/ui/thumbnail';

export function severityClass(level: number) {
  if (level >= 4) return 'bg-[#ffe8df] text-[#9b3518]';
  if (level === 3) return 'bg-[#fff1c7] text-[#765300]';
  return 'bg-signal/15 text-moss';
}

export function SeverityChip({ level }: { level: number }) {
  return <span className={`rounded-full px-2.5 py-1 text-[11px] font-bold ${severityClass(level)}`}>Severity {level}</span>;
}

/** The video screenshot, else the incident's first evidence image, else a placeholder. */
export function IncidentThumbnail({ urls, className = 'aspect-video' }: { urls: (string | undefined)[]; className?: string }) {
  const candidates = urls.filter((url): url is string => Boolean(url));
  const [failed, setFailed] = useState(0);
  const view = reportThumbnailView(candidates[failed], failed >= candidates.length);
  return (
    <div aria-label="Video screenshot preview" className={`relative overflow-hidden bg-[#dfe3dc] ${className}`}>
      {view.kind === 'image' ? (
        <img
          alt=""
          className="h-full w-full object-cover"
          loading={view.loading}
          onError={() => setFailed((count) => count + 1)}
          src={view.src}
        />
      ) : (
        <div className="absolute inset-0 grid place-items-center bg-gradient-to-br from-white/35 to-transparent">
          <div className="h-10 w-14 rounded-xl bg-white/55" />
        </div>
      )}
    </div>
  );
}

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
  return (
    <label>
      <span className="sr-only">{label}</span>
      <select aria-label={label} className="control" onChange={(event) => onChange(event.target.value)} value={value}>
        {options.map(([key, text]) => (
          <option key={key} value={key}>
            {text}
          </option>
        ))}
      </select>
    </label>
  );
}

export function FilterChip({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-ink/12 bg-white py-1 pl-3 pr-1.5 text-xs font-semibold">
      {label}
      <button
        aria-label={`Remove filter ${label}`}
        className="grid h-5 w-5 place-items-center rounded-full bg-ink/8 text-[11px] hover:bg-ink/15"
        onClick={onRemove}
        type="button"
      >
        x
      </button>
    </span>
  );
}

export function CardSkeleton({ count = 6, label }: { count?: number; label: string }) {
  return (
    <div className="mt-5 grid gap-5 md:grid-cols-2 xl:grid-cols-3" role="status">
      <span className="sr-only">{label}</span>
      {Array.from({ length: count }, (_, index) => (
        <div className="animate-pulse overflow-hidden rounded-[1.5rem] border border-ink/10 bg-white" key={index}>
          <div className="aspect-video bg-ink/10" />
          <div className="space-y-3 p-5">
            <div className="h-5 w-2/3 rounded bg-ink/10" />
            <div className="h-4 rounded bg-ink/10" />
            <div className="h-4 w-4/5 rounded bg-ink/10" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ErrorPanel({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="mt-8 rounded-2xl border border-clay/30 bg-white p-8 text-center" role="alert">
      <p className="text-clay">{message}</p>
      <button className="mt-4 font-semibold text-moss" onClick={onRetry} type="button">
        Try again
      </button>
    </div>
  );
}
