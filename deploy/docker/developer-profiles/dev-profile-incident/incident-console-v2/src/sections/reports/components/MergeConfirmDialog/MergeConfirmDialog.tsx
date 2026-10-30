// SPDX-License-Identifier: Apache-2.0
'use client';

import { GitMergeIcon } from 'lucide-react';
import { useState } from 'react';

import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { officialMergeWarning } from '@/lib/reports/merge-flow';
import { pluralVideos } from '@/lib/reports/merge-target';

export interface MergeSide {
  incidentId: number;
  videoNames: readonly string[];
}

/**
 * The confirmation both merges share, the manual one and a suggestion's Accept: `source` is deleted and its videos move
 * into `target`, whose report is then rebuilt. `onConfirm` does the work and throws an Error worded for the reviewer; the
 * dialog stays open and shows it. The caller closes the dialog when `onConfirm` resolves.
 */
export function MergeConfirmDialog({
  open,
  source,
  target,
  targetHasOfficial,
  onBack,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  source: MergeSide;
  target: MergeSide;
  targetHasOfficial: boolean;
  /** Offered by the manual merge, which came from the picker. */
  onBack?: () => void;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}) {
  const [merging, setMerging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setMerging(true);
    setError(null);
    try {
      await onConfirm();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not merge the incidents. Nothing was changed.');
    } finally {
      setMerging(false);
    }
  }

  const total = target.videoNames.length + source.videoNames.length;
  const official = officialMergeWarning({ incidentId: target.incidentId, hasOfficial: targetHasOfficial }, source.videoNames);
  const leave = () => {
    if (merging) return;
    setError(null);
    (onBack ?? onCancel)();
  };
  return (
    <AlertDialog onOpenChange={(next) => !next && leave()} open={open}>
      <AlertDialogContent data-testid="merge-confirm">
        <AlertDialogHeader>
          <div className="flex items-start gap-3">
            <div className="grid size-9 shrink-0 place-items-center rounded-full bg-muted text-primary">
              <GitMergeIcon className="size-4" />
            </div>
            <div className="grid min-w-0 gap-1.5 text-left">
              <AlertDialogTitle>
                Merge Incident {source.incidentId} into Incident {target.incidentId}?
              </AlertDialogTitle>
              <AlertDialogDescription>
                The {pluralVideos(source.videoNames.length)} move to Incident {target.incidentId}, which then holds{' '}
                <strong className="text-foreground">{pluralVideos(total)}</strong>. Incident {source.incidentId} is deleted.
              </AlertDialogDescription>
            </div>
          </div>
        </AlertDialogHeader>
        <div className="rounded-lg border bg-muted/40 p-3" data-testid="merge-summary">
          <p className="text-xs font-bold">
            Incident {target.incidentId} after the merge · {pluralVideos(total)}
          </p>
          <ul className="mt-2 grid gap-1.5 font-mono text-xs">
            {target.videoNames.map((name) => (
              <li className="flex items-center justify-between gap-2" key={name}>
                <span className="min-w-0 break-all">{name}</span>
                <Badge className="shrink-0" variant="secondary">
                  already here
                </Badge>
              </li>
            ))}
            {source.videoNames.map((name) => (
              <li className="flex items-center justify-between gap-2" key={name}>
                <span className="min-w-0 break-all">{name}</span>
                <Badge className="shrink-0" variant="outline">
                  moves in
                </Badge>
              </li>
            ))}
          </ul>
        </div>
        <ul className="grid list-disc gap-2 pl-5 text-sm leading-5 text-muted-foreground">
          <li>Incident {source.incidentId}&apos;s versions, edits and official choice are not carried over, and its link stops working.</li>
          <li>Incident {target.incidentId} keeps its versions.</li>
          <li>
            Incident {target.incidentId}&apos;s report is rebuilt from the stored analyses of all {pluralVideos(total)} as a new version. No
            video is analysed again.
          </li>
          {official && (
            <li className="font-semibold text-foreground" data-testid="merge-official-warning">
              {official}
            </li>
          )}
          <li>No video files move. This cannot be undone.</li>
        </ul>
        {error && (
          <Alert data-testid="merge-error" role="alert" variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        <AlertDialogFooter>
          <Button disabled={merging} onClick={leave} type="button" variant="outline">
            {onBack ? 'Back' : 'Cancel'}
          </Button>
          <Button data-testid="merge-confirm-button" disabled={merging} onClick={() => void confirm()} type="button">
            {merging ? 'Merging and rebuilding...' : 'Merge incidents'}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
