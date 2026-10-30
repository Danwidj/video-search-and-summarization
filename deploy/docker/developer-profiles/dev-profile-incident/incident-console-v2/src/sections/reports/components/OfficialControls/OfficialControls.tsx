// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';
import { Loader2 } from 'lucide-react';

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog';
import { Button } from '@/components/ui/button';
import { clearOfficial, markOfficial } from '@/lib/reports/official-client';

/**
 * Explicit official-revision selection for a video. Nothing becomes official
 * by itself; a reviewer marks one revision, which also embeds its evidence for
 * search, and can move or clear the mark. No name is recorded.
 */
export function OfficialControls({
  incidentId,
  revisionId,
  isOfficial,
  hasOfficial,
  onChanged,
}: {
  incidentId: string;
  revisionId: number;
  isOfficial: boolean;
  hasOfficial: boolean;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function execute(action: 'select' | 'clear') {
    setBusy(true);
    try {
      await (action === 'select' ? markOfficial(incidentId, revisionId) : clearOfficial(incidentId));
      onChanged();
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Update failed');
    } finally {
      setBusy(false);
    }
  }

  function handleAction(action: 'select' | 'clear') {
    if (action === 'select' && hasOfficial) {
      setConfirmOpen(true);
      return;
    }
    void execute(action);
  }

  return (
    <>
      {isOfficial ? (
        <Button
          data-testid="clear-official"
          disabled={busy}
          onClick={() => handleAction('clear')}
          size="sm"
          type="button"
          variant="outline"
        >
          {busy ? (
            <>
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              Clearing…
            </>
          ) : (
            'Clear official report'
          )}
        </Button>
      ) : (
        <Button
          data-testid="make-official"
          disabled={busy}
          onClick={() => handleAction('select')}
          size="sm"
          type="button"
          variant="default"
        >
          {busy ? (
            <>
              <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              Marking official…
            </>
          ) : (
            'Make this the official report'
          )}
        </Button>
      )}

      <AlertDialog onOpenChange={setConfirmOpen} open={confirmOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Replace official report?</AlertDialogTitle>
            <AlertDialogDescription>
              Another version is currently the official report for this video. Replace it with this one?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction onClick={() => void execute('select')}>Replace official</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      <AlertDialog onOpenChange={(open) => !open && setErrorMessage(null)} open={errorMessage !== null}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Update failed</AlertDialogTitle>
            <AlertDialogDescription>{errorMessage}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogAction onClick={() => setErrorMessage(null)}>OK</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
