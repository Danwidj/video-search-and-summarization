// SPDX-License-Identifier: Apache-2.0
'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

import { Button } from '@/components/ui/button';
import { DeleteIncidentDialog } from '@/sections/library/components/IncidentCard/DeleteIncidentDialog';

/**
 * The page of an incident that holds no videos (older data; the app never creates one): there is nothing to
 * report on, so it says so and offers the library's Delete incident action.
 */
export function EmptyIncident({ incidentId }: { incidentId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState('');

  async function remove() {
    setBusy(true);
    setProblem('');
    try {
      const response = await fetch(`/api/reports/${encodeURIComponent(incidentId)}/delete`, { method: 'DELETE' });
      const payload = (await response.json()) as { error?: string };
      if (!response.ok) throw new Error(payload.error || 'Delete failed');
      router.push('/library');
    } catch (cause) {
      setProblem(cause instanceof Error ? cause.message : 'Delete failed');
      setBusy(false);
    }
  }

  return (
    <div className="pb-16" data-testid="empty-incident">
      <div className="overflow-hidden border-y border-border bg-card shadow-panel">
        <div className="border-b border-border px-5 py-4 sm:px-8">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-amber-800">No videos</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight">Incident {incidentId} has no videos</h1>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            There is nothing to report on, and it cannot be merged into. Delete the incident to remove it from the library.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 px-5 py-4 sm:px-8">
          <Button disabled={busy} onClick={() => setOpen(true)} type="button" variant="destructive">
            Delete incident
          </Button>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
        </div>
        <div className="border-t border-border px-5 py-3 text-xs sm:px-8">
          <Link className="font-semibold text-moss hover:underline" href="/library">
            Back to the library
          </Link>
        </div>
      </div>
      <DeleteIncidentDialog
        busy={busy}
        item={{
          title: `Incident ${incidentId}`,
          incidentType: '',
          videoCount: 0,
          firstVideoName: null,
          versionCount: 0,
          isOfficial: false,
        }}
        onConfirm={remove}
        onOpenChange={setOpen}
        open={open}
      />
    </div>
  );
}
