// SPDX-License-Identifier: Apache-2.0
'use client';

import { useEffect, useState } from 'react';
import { DownloadIcon, FileTextIcon, Loader2Icon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { DEFAULT_REPORT_PDF_OPTIONS, type ReportPdfOptions } from '@/lib/reports/report-pdf-markdown';
import type { RevisionSummary } from '@/modules/reports/domain/revision';

type Status = 'idle' | 'rendering' | 'ready' | 'failed';

const OPTION_LABELS: Array<[keyof ReportPdfOptions, string]> = [
  ['includeImages', 'Evidence snapshots'],
  ['includeTimeline', 'Timeline table'],
  ['includeHistory', 'Version history'],
];

/**
 * Makes a PDF (or Markdown) of one version of the report on the server. Nothing is saved to the report: the file is the only
 * output, and a failure shows the agent's reason with Try again. There is no browser-print fallback.
 */
export function ReportPdfDialog({
  videoId,
  title,
  revisions,
  currentRevisionId,
}: {
  videoId: string;
  title: string;
  revisions: RevisionSummary[];
  currentRevisionId: number;
}) {
  const [open, setOpen] = useState(false);
  const [revisionId, setRevisionId] = useState(currentRevisionId);
  const [options, setOptions] = useState<ReportPdfOptions>(DEFAULT_REPORT_PDF_OPTIONS);
  const [status, setStatus] = useState<Status>('idle');
  const [error, setError] = useState('');
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [missing, setMissing] = useState(0);

  // The file is the output: release it when the dialog closes or a new one replaces it.
  useEffect(
    () => () => {
      if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    },
    [pdfUrl],
  );

  async function request(format: 'pdf' | 'markdown'): Promise<Response> {
    return fetch(`/api/reports/${encodeURIComponent(videoId)}/pdf`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ format, revisionId, options }),
    });
  }

  async function generate() {
    setStatus('rendering');
    setError('');
    try {
      const response = await request('pdf');
      if (!response.ok) {
        const body = (await response.json().catch(() => null)) as { error?: string } | null;
        throw new Error(body?.error ?? 'The PDF could not be made. Try again.');
      }
      const blob = await response.blob();
      setPdfUrl(URL.createObjectURL(blob));
      setMissing(Number(response.headers.get('x-missing-images') ?? 0));
      setStatus('ready');
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The PDF could not be made. Try again.');
      setStatus('failed');
    }
  }

  async function openMarkdown() {
    const response = await request('markdown');
    if (!response.ok) {
      setError('The Markdown could not be made. Try again.');
      setStatus('failed');
      return;
    }
    const url = URL.createObjectURL(await response.blob());
    window.open(url, '_blank', 'noopener');
    setTimeout(() => URL.revokeObjectURL(url), 60_000);
  }

  function changed(next: () => void) {
    next();
    if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    setPdfUrl(null);
    setStatus('idle');
  }

  return (
    <Dialog onOpenChange={setOpen} open={open}>
      <DialogTrigger asChild>
        <Button className="text-xs font-semibold" size="sm" type="button" variant="outline">
          <DownloadIcon aria-hidden="true" data-icon="inline-start" />
          Download PDF
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>Download PDF</DialogTitle>
          <DialogDescription>A report in the VSS look: A4, with the running header and page numbers.</DialogDescription>
        </DialogHeader>
        <div className="grid gap-5 sm:grid-cols-[minmax(0,1fr)_16rem]">
          <section
            aria-label="Preview"
            className="mx-auto flex aspect-[1/1.414] w-full max-w-xs flex-col gap-2 border border-border bg-white p-5 shadow-sm"
          >
            <span className="font-mono text-[9px] font-bold uppercase tracking-[0.12em] text-primary">Incident report</span>
            <span className="border-b-2 border-primary pb-1 text-sm font-bold leading-snug">{title}</span>
            <span className="mt-2 h-2 w-4/5 rounded bg-muted" />
            <span className="h-2 w-full rounded bg-muted" />
            <span className="h-2 w-3/5 rounded bg-muted" />
            <span className="mt-3 border-b border-primary/70 pb-0.5 text-[10px] font-semibold">Evidence</span>
            <span className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-2">
              <span className="aspect-video rounded bg-muted" />
              <span className="flex flex-col gap-1.5">
                <span className="h-2 rounded bg-muted" />
                <span className="h-2 w-4/5 rounded bg-muted" />
              </span>
            </span>
          </section>
          <div className="flex flex-col gap-4 text-sm">
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-semibold text-muted-foreground">Version</span>
              <Select onValueChange={(value) => changed(() => setRevisionId(Number(value)))} value={String(revisionId)}>
                <SelectTrigger aria-label="Version" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {revisions.map((revision) => (
                    <SelectItem key={revision.revisionId} value={String(revision.revisionId)}>
                      v{revision.revisionNo} · {revision.kind === 'human' ? 'Human' : 'Model'}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <fieldset className="flex flex-col gap-2">
              <legend className="mb-1 text-xs font-semibold text-muted-foreground">Include</legend>
              {OPTION_LABELS.map(([key, label]) => (
                <label className="flex items-center gap-2" key={key}>
                  <input
                    checked={options[key]}
                    className="size-4 accent-primary"
                    onChange={(event) => changed(() => setOptions((current) => ({ ...current, [key]: event.target.checked })))}
                    type="checkbox"
                  />
                  {label}
                </label>
              ))}
            </fieldset>
            {status === 'failed' && (
              <p className="m-0 rounded-md border border-destructive/30 bg-destructive/5 p-2 text-xs text-destructive" role="alert">
                {error}
              </p>
            )}
            {status === 'ready' && missing > 0 && (
              <p className="m-0 text-xs text-muted-foreground">{missing} snapshot(s) could not be loaded and are noted in the PDF.</p>
            )}
          </div>
        </div>
        <DialogFooter className="flex-wrap gap-2 sm:justify-between">
          <Button onClick={() => void openMarkdown()} size="sm" type="button" variant="outline">
            <FileTextIcon aria-hidden="true" data-icon="inline-start" />
            Open Markdown
          </Button>
          <div className="flex flex-wrap gap-2">
            {status === 'failed' || status === 'idle' ? (
              <Button onClick={() => void generate()} size="sm" type="button">
                {status === 'failed' ? 'Try again' : 'Generate PDF'}
              </Button>
            ) : status === 'rendering' ? (
              <Button disabled size="sm" type="button">
                <Loader2Icon aria-hidden="true" className="animate-spin" data-icon="inline-start" />
                Generating…
              </Button>
            ) : (
              <>
                <Button onClick={() => void generate()} size="sm" type="button" variant="outline">
                  Generate again
                </Button>
                <Button asChild size="sm">
                  <a
                    download={`${videoId}-v${revisions.find((r) => r.revisionId === revisionId)?.revisionNo ?? ''}.pdf`}
                    href={pdfUrl ?? undefined}
                  >
                    <DownloadIcon aria-hidden="true" data-icon="inline-start" />
                    Download PDF
                  </a>
                </Button>
              </>
            )}
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
