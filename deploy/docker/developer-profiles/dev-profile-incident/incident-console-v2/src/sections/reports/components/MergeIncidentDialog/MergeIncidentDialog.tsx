// SPDX-License-Identifier: Apache-2.0
'use client';

import { GitMergeIcon } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { mergeIncidentInto } from '@/lib/reports/merge-client';
import {
  type MergeCandidate,
  type MergeCandidateSource,
  mergeCandidates,
  mergedVideoCount,
  pluralVideos,
} from '@/lib/reports/merge-target';

type Step = 'closed' | 'pick' | 'confirm';

/**
 * Merges this incident into another one the reviewer picks, after a confirmation. The picked incident is kept and
 * this one is deleted, so on success the page moves to the kept incident.
 */
export function MergeIncidentDialog({ incidentId, videoNames }: { incidentId: number; videoNames: readonly string[] }) {
  const router = useRouter();
  const [step, setStep] = useState<Step>('closed');
  const [candidates, setCandidates] = useState<MergeCandidate[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [targetId, setTargetId] = useState<string>('');
  const [merging, setMerging] = useState(false);

  useEffect(() => {
    if (step !== 'pick' || candidates) return;
    const controller = new AbortController();
    setLoadError(null);
    fetch('/api/reports?all=true', { cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        const payload = (await response.json().catch(() => ({}))) as { reports?: MergeCandidateSource[]; error?: string };
        if (!response.ok || !payload.reports) throw new Error(payload.error || 'Could not load the incidents');
        setCandidates(mergeCandidates(payload.reports, incidentId));
      })
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setLoadError(cause instanceof Error ? cause.message : 'Could not load the incidents');
      });
    return () => controller.abort();
  }, [step, candidates, incidentId]);

  const target = candidates?.find((candidate) => String(candidate.incidentId) === targetId) ?? null;
  const close = () => {
    setStep('closed');
    setTargetId('');
  };

  async function merge() {
    if (!target) return;
    setMerging(true);
    try {
      await mergeIncidentInto(incidentId, target.incidentId);
      toast.success(`Incident ${incidentId} merged into Incident ${target.incidentId}`);
      close();
      router.push(`/reports/${target.incidentId}`);
    } catch (cause) {
      toast.error(cause instanceof Error ? cause.message : 'Could not merge the incidents');
      setStep('pick');
    } finally {
      setMerging(false);
    }
  }

  return (
    <>
      <Button
        className="text-xs font-semibold"
        data-testid="merge-open"
        onClick={() => setStep('pick')}
        size="sm"
        type="button"
        variant="outline"
      >
        <GitMergeIcon data-icon="inline-start" />
        Merge into another incident
      </Button>

      <Dialog onOpenChange={(open) => !open && close()} open={step === 'pick'}>
        <DialogContent className="sm:max-w-md" data-testid="merge-pick">
          <DialogHeader>
            <DialogTitle>Merge into another incident</DialogTitle>
            <DialogDescription>
              Move all {pluralVideos(videoNames.length)} of <strong className="text-foreground">Incident {incidentId}</strong> into the
              incident you pick. Incident {incidentId} is then deleted.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-3">
            <div className="grid gap-2">
              <Label className="text-xs font-bold" htmlFor="merge-target">
                Merge into
              </Label>
              <Select disabled={!candidates?.length} onValueChange={setTargetId} value={targetId}>
                <SelectTrigger className="w-full" id="merge-target">
                  <SelectValue
                    placeholder={candidates ? (candidates.length ? 'Choose an incident' : 'No other incident') : 'Loading incidents...'}
                  />
                </SelectTrigger>
                <SelectContent>
                  {(candidates ?? []).map((candidate) => (
                    <SelectItem key={candidate.incidentId} value={String(candidate.incidentId)}>
                      <span className="grid min-w-0">
                        <span className="truncate text-sm font-medium">{candidate.label}</span>
                        <span className="truncate font-mono text-xs text-muted-foreground">{candidate.detail}</span>
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {loadError ? (
                <p className="text-xs text-destructive" role="alert">
                  {loadError}
                </p>
              ) : null}
            </div>
            {target ? (
              <div className="rounded-lg border bg-muted/40 p-3" data-testid="merge-summary">
                <p className="text-xs font-bold">
                  Incident {target.incidentId} after the merge · {pluralVideos(mergedVideoCount(target, videoNames.length))}
                </p>
                <ul className="mt-2 grid gap-1.5 font-mono text-xs">
                  <li className="flex items-center justify-between gap-2">
                    <span>{pluralVideos(target.videoCount)}</span>
                    <Badge variant="secondary">already here</Badge>
                  </li>
                  {videoNames.map((name) => (
                    <li className="flex items-center justify-between gap-2" key={name}>
                      <span className="min-w-0 break-all">{name}</span>
                      <Badge className="shrink-0" variant="outline">
                        moves in
                      </Badge>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
          <DialogFooter>
            <Button onClick={close} type="button" variant="outline">
              Cancel
            </Button>
            <Button data-testid="merge-review" disabled={!target} onClick={() => setStep('confirm')} type="button">
              Review merge
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <AlertDialog onOpenChange={(open) => !open && !merging && setStep('pick')} open={step === 'confirm'}>
        <AlertDialogContent data-testid="merge-confirm">
          <AlertDialogHeader>
            <div className="flex items-start gap-3">
              <div className="grid size-9 shrink-0 place-items-center rounded-full bg-muted text-primary">
                <GitMergeIcon className="size-4" />
              </div>
              <div className="grid gap-1.5 text-left">
                <AlertDialogTitle>
                  Merge Incident {incidentId} into Incident {target?.incidentId}?
                </AlertDialogTitle>
                <AlertDialogDescription>
                  The {pluralVideos(videoNames.length)} move to Incident {target?.incidentId}, which then holds{' '}
                  <strong className="text-foreground">
                    {pluralVideos(target ? mergedVideoCount(target, videoNames.length) : videoNames.length)}
                  </strong>
                  . Incident {incidentId} is deleted.
                </AlertDialogDescription>
              </div>
            </div>
          </AlertDialogHeader>
          <ul className="grid list-disc gap-2 pl-5 text-sm leading-5 text-muted-foreground">
            <li>Incident {incidentId}&apos;s versions, edits and official choice are not carried over, and its link stops working.</li>
            <li>Incident {target?.incidentId} keeps its versions and its official version.</li>
            <li>
              The report is not regenerated. Incident {target?.incidentId}&apos;s latest version will say{' '}
              <em className="font-semibold not-italic text-foreground">Does not include: {videoNames.join(', ')}</em> until you press
              Regenerate.
            </li>
            <li>No video files move. This cannot be undone.</li>
          </ul>
          <AlertDialogFooter>
            <Button disabled={merging} onClick={() => setStep('pick')} type="button" variant="outline">
              Back
            </Button>
            <Button data-testid="merge-confirm-button" disabled={merging} onClick={() => void merge()} type="button">
              {merging ? 'Merging...' : 'Merge incidents'}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
