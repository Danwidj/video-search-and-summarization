// SPDX-License-Identifier: Apache-2.0
'use client';

import { useState } from 'react';
import { Trash2Icon } from 'lucide-react';

import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import type { ReportLibraryItem } from '@/modules/reports/domain/storage';

export function DeleteIncidentDialog({
  item,
  open,
  onOpenChange,
  onConfirm,
  busy,
}: {
  item: ReportLibraryItem;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: (item: ReportLibraryItem) => void;
  busy: boolean;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const versions = item.versionCount ?? 0;
  const evidence = item.evidenceCount ?? 0;
  const title = item.title || item.incident_type;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) setConfirmed(false);
        onOpenChange(next);
      }}
    >
      <DialogContent className="sm:max-w-md bg-white">
        <DialogHeader className="gap-3">
          <div className="flex items-start gap-3">
            <div className="grid size-9 shrink-0 place-items-center rounded-full bg-destructive/10 text-destructive">
              <Trash2Icon className="size-4 text-destructive" />
            </div>
            <div className="min-w-0">
              <DialogTitle className="text-base font-semibold">Delete this incident?</DialogTitle>
              <div className="mt-1 text-sm text-ink/70">
                <strong className="font-semibold text-ink">{title}</strong>
                <br />
                <span className="break-all font-mono text-xs">{item.filename}</span>
              </div>
            </div>
          </div>
          <DialogDescription className="mt-2 text-sm leading-5 text-ink/70">
            This permanently deletes the video from storage and all{' '}
            <strong className="text-ink">
              {versions} {versions === 1 ? 'version' : 'versions'}
            </strong>
            {item.isOfficial ? ', including the official one' : ''}, with their {evidence} evidence {evidence === 1 ? 'image' : 'images'}.
            It cannot be undone.
          </DialogDescription>
        </DialogHeader>

        <div className="mt-4 flex items-start gap-2">
          <Checkbox
            id="confirm-delete"
            checked={confirmed}
            onCheckedChange={(checked) => setConfirmed(checked === true)}
            className="mt-0.5 data-[state=checked]:bg-destructive data-[state=checked]:border-destructive"
          />
          <Label htmlFor="confirm-delete" className="cursor-pointer text-sm font-normal text-ink/80">
            I understand this cannot be undone.
          </Label>
        </div>

        <DialogFooter className="mt-5 flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)} type="button">
            Cancel
          </Button>
          <Button
            variant="destructive"
            disabled={!confirmed || busy}
            onClick={() => {
              onConfirm(item);
              onOpenChange(false);
            }}
            type="button"
          >
            Delete incident
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
