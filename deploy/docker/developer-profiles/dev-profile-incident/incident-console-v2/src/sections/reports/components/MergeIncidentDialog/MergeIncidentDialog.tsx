// SPDX-License-Identifier: Apache-2.0
'use client';

import { GitMergeIcon } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { incidentNotices, incidentScope } from '@/lib/reports/incident-notices';
import { requestReportBuild, fetchIncidentVideos, type IncidentVideos, mergeIncidentInto } from '@/lib/reports/merge-client';
import { mergedNotice, mergeThenRebuild } from '@/lib/reports/merge-flow';
import { type MergeCandidate, type MergeCandidateSource, mergeCandidates, pluralVideos } from '@/lib/reports/merge-target';
import { MergeConfirmDialog } from '@/sections/reports/components/MergeConfirmDialog';

type Step = 'closed' | 'pick' | 'confirm';

/**
 * Merges this incident into another one the reviewer picks, after a confirmation. The picked incident is kept and
 * this one is deleted, so on success its report is rebuilt and the page moves to the kept incident, which shows the result.
 */
export function MergeIncidentDialog({ incidentId, videoNames }: { incidentId: number; videoNames: readonly string[] }) {
  const router = useRouter();
  const [step, setStep] = useState<Step>('closed');
  const [candidates, setCandidates] = useState<MergeCandidate[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [targetId, setTargetId] = useState<string>('');
  const [targetVideos, setTargetVideos] = useState<IncidentVideos | null>(null);
  const [targetError, setTargetError] = useState<string | null>(null);

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
  const targetIncidentId = target?.incidentId ?? null;

  useEffect(() => {
    setTargetVideos(null);
    setTargetError(null);
    if (targetIncidentId === null) return;
    const controller = new AbortController();
    fetchIncidentVideos(targetIncidentId, controller.signal)
      .then(setTargetVideos)
      .catch((cause: unknown) => {
        if (!controller.signal.aborted) setTargetError(cause instanceof Error ? cause.message : 'Could not read the incident');
      });
    return () => controller.abort();
  }, [targetIncidentId]);

  const close = () => {
    setStep('closed');
    setTargetId('');
  };

  async function merge() {
    if (!target || !targetVideos) return;
    const rebuilt = await mergeThenRebuild(
      { merge: () => mergeIncidentInto(incidentId, target.incidentId), build: requestReportBuild },
      target.incidentId,
    );
    incidentNotices.set(
      incidentScope(target.incidentId),
      mergedNotice({ keptIncidentId: target.incidentId, videoCount: targetVideos.videoNames.length + videoNames.length, rebuilt }),
    );
    close();
    router.push(`/reports/${target.incidentId}`);
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
            {target && targetError ? (
              <p className="text-xs text-destructive" role="alert">
                {targetError}
              </p>
            ) : target ? (
              <div className="rounded-lg border bg-muted/40 p-3" data-testid="merge-summary">
                <p className="text-xs font-bold">
                  Incident {target.incidentId} after the merge ·{' '}
                  {targetVideos ? pluralVideos(targetVideos.videoNames.length + videoNames.length) : 'loading videos...'}
                </p>
                <ul className="mt-2 grid gap-1.5 font-mono text-xs">
                  {(targetVideos?.videoNames ?? []).map((name) => (
                    <li className="flex items-center justify-between gap-2" key={name}>
                      <span className="min-w-0 break-all">{name}</span>
                      <Badge className="shrink-0" variant="secondary">
                        already here
                      </Badge>
                    </li>
                  ))}
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
            <Button data-testid="merge-review" disabled={!targetVideos} onClick={() => setStep('confirm')} type="button">
              Review merge
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {target && targetVideos && (
        <MergeConfirmDialog
          onBack={() => setStep('pick')}
          onCancel={close}
          onConfirm={merge}
          open={step === 'confirm'}
          source={{ incidentId, videoNames }}
          target={{ incidentId: target.incidentId, videoNames: targetVideos.videoNames }}
          targetHasOfficial={targetVideos.hasOfficial}
        />
      )}
    </>
  );
}
