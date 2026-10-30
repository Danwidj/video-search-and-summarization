// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { GitBranchIcon, Trash2Icon } from 'lucide-react';
import { useRef, useState } from 'react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Progress } from '@/components/ui/progress';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { incidentNotices, incidentScope } from '@/lib/reports/incident-notices';
import {
  buildFirstReport,
  defaultRemoveChoice,
  effectiveRemoveChoice,
  incidentHref,
  includingOfficial,
  isLastVideo,
  removeChoices,
  removedNotice,
  removeVideo,
  staleReportNote,
  type RemoveChoice,
} from '@/lib/reports/remove-video';

type Step =
  | { name: 'choose' }
  | { name: 'confirm' }
  | { name: 'working'; label: string; percent: number }
  | { name: 'moved'; newIncidentId: number; reportError: string | null };

const noun = (count: number, one: string, many: string) => `${count} ${count === 1 ? one : many}`;
const otherVideos = (count: number) => (count === 1 ? 'other video' : `other ${count} videos`);
const allVersions = (count: number) => (count === 1 ? 'its version' : `all ${count} versions`);

/**
 * Removes the selected camera's video from its incident. Two choices: move it to an incident of its own (which then
 * builds its first report, shown with progress and a link) or delete it entirely (behind a confirmation). The last
 * video can only be deleted, and the incident goes with it. The current incident's report is not regenerated.
 */
export function RemoveVideoDialog({
  incidentId,
  video: current,
  videoCount,
  versionCount,
  hasOfficial,
  title,
  onRemoved,
}: {
  incidentId: string;
  /** The real file name of the selected camera's video. */
  video: string;
  /** Videos currently in the incident (not only in the open version), this one included. */
  videoCount: number;
  versionCount: number | null;
  /** The incident has an official version; deleting the incident then deletes it too. */
  hasOfficial: boolean;
  title: string;
  /** The video left the incident but the incident is still there: the page reloads without that camera. */
  onRemoved: () => void;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  // The page reloads without the camera while the dialog is still showing the result, so the name is pinned at open.
  const [video, setVideo] = useState(current);
  const [step, setStep] = useState<Step>({ name: 'choose' });
  const [picked, setPicked] = useState<RemoveChoice>(defaultRemoveChoice(videoCount));
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const last = isLastVideo(videoCount);
  // The video count changes while the page stays mounted, so a pick that is no longer offered falls back to the default.
  const choice = effectiveRemoveChoice(picked, videoCount);
  const working = step.name === 'working';

  const reset = () => {
    setStep({ name: 'choose' });
    setPicked(defaultRemoveChoice(videoCount));
    setConfirmed(false);
    setError(null);
  };

  const change = (next: boolean) => {
    if (working) return;
    if (next) setVideo(current);
    setOpen(next);
    if (!next) reset();
  };

  async function runDelete() {
    setError(null);
    setStep({ name: 'working', label: last ? 'Deleting the video and the incident' : 'Deleting the video', percent: 50 });
    try {
      const outcome = await removeVideo(video, 'delete');
      if (outcome.choice === 'delete' && outcome.incidentDeleted) {
        setOpen(false);
        router.push('/library');
        return;
      }
      setOpen(false);
      reset();
      incidentNotices.set(incidentScope(Number(incidentId)), removedNotice(video, 'delete', Number(incidentId)));
      onRemoved();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not remove the video');
      setStep({ name: 'confirm' });
    }
  }

  async function runMove() {
    setError(null);
    setStep({ name: 'working', label: 'Moving the video to its own incident', percent: 25 });
    let newIncidentId: number;
    try {
      const outcome = await removeVideo(video, 'move');
      if (outcome.choice !== 'move') throw new Error('The video was not moved');
      newIncidentId = outcome.newIncidentId;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not move the video');
      setStep({ name: 'choose' });
      return;
    }
    // The video has left this incident; reload the page behind the dialog so the camera is gone.
    incidentNotices.set(incidentScope(Number(incidentId)), removedNotice(video, 'move', Number(incidentId), newIncidentId));
    onRemoved();
    setStep({ name: 'working', label: `Building the first report of Incident #${newIncidentId}`, percent: 60 });
    try {
      await buildFirstReport(newIncidentId);
      setStep({ name: 'moved', newIncidentId, reportError: null });
    } catch (cause) {
      setStep({ name: 'moved', newIncidentId, reportError: cause instanceof Error ? cause.message : 'Could not build the report' });
    }
  }

  const primary = () => {
    if (choice === 'move') void runMove();
    else setStep({ name: 'confirm' });
  };

  return (
    <Dialog onOpenChange={change} open={open}>
      <DialogTrigger asChild>
        <Button className="text-xs font-semibold" data-testid="remove-video" size="sm" type="button" variant="outline">
          Remove video
        </Button>
      </DialogTrigger>
      <DialogContent
        className="bg-white sm:max-w-md"
        onInteractOutside={(event) => working && event.preventDefault()}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          cancelRef.current?.focus();
        }}
      >
        {step.name === 'choose' && (
          <>
            <DialogHeader className="gap-2 pr-8">
              <DialogTitle className="break-all">Remove {video}</DialogTitle>
              <DialogDescription>
                {last
                  ? `This is the last video in Incident #${incidentId}.`
                  : `Incident #${incidentId} keeps its ${otherVideos(videoCount - 1)}. Choose what happens to this one.`}
              </DialogDescription>
            </DialogHeader>
            <ToggleGroup
              aria-label="What to do with the video"
              className="grid w-full gap-2"
              onValueChange={(next) => next && setPicked(next as RemoveChoice)}
              orientation="vertical"
              spacing={2}
              type="single"
              value={choice}
              variant="outline"
            >
              {removeChoices(videoCount).includes('move') && (
                <ToggleGroupItem
                  className="h-auto w-full items-start justify-start gap-3 whitespace-normal px-3 py-3 text-left"
                  value="move"
                >
                  <GitBranchIcon className="mt-0.5 size-4 shrink-0 text-primary" />
                  <span className="grid gap-0.5">
                    <span className="text-sm font-semibold">Move to its own incident</span>
                    <span className="text-xs font-normal leading-5 text-muted-foreground">
                      Creates a new incident with this video and its stored analysis. Its first report is built automatically.
                    </span>
                  </span>
                </ToggleGroupItem>
              )}
              <ToggleGroupItem
                className="h-auto w-full items-start justify-start gap-3 whitespace-normal px-3 py-3 text-left"
                value="delete"
              >
                <Trash2Icon className="mt-0.5 size-4 shrink-0 text-destructive" />
                <span className="grid gap-0.5">
                  <span className="text-sm font-semibold">{last ? 'Delete the video and the incident' : 'Delete entirely'}</span>
                  <span className="text-xs font-normal leading-5 text-muted-foreground">
                    {last
                      ? `Deletes the video, its analysis, evidence images and the stored file. Because nothing is left in the incident, Incident #${incidentId} and ${versionCount === null ? 'its versions' : noun(versionCount, 'version', 'versions')}${includingOfficial(hasOfficial)} are deleted too.`
                      : 'Deletes the video, its analysis, evidence images and the stored file. This cannot be undone.'}
                  </span>
                </span>
              </ToggleGroupItem>
            </ToggleGroup>
            {!last && (
              <p className="text-xs leading-5 text-muted-foreground">
                Either way, the camera leaves Incident #{incidentId}. Its older versions stay as history and say &quot;Includes a removed
                video: {video}&quot;. The report is not regenerated; press Regenerate afterwards.
              </p>
            )}
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <DialogFooter className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button onClick={() => change(false)} ref={cancelRef} type="button" variant="outline">
                Cancel
              </Button>
              <Button onClick={primary} type="button" variant={choice === 'delete' ? 'destructive' : 'default'}>
                {choice === 'delete' ? (last ? 'Delete video and incident…' : 'Delete video…') : 'Move to new incident'}
              </Button>
            </DialogFooter>
          </>
        )}

        {step.name === 'confirm' && (
          <>
            <DialogHeader className="gap-3">
              <div className="flex items-start gap-3">
                <div className="grid size-9 shrink-0 place-items-center rounded-full bg-destructive/10 text-destructive">
                  <Trash2Icon className="size-4" />
                </div>
                <div className="min-w-0">
                  <DialogTitle className="text-base font-semibold">
                    {last ? `Delete Incident #${incidentId}?` : 'Delete this video?'}
                  </DialogTitle>
                  <div className="mt-1 text-sm text-muted-foreground">
                    <strong className="font-semibold text-foreground">{title}</strong>
                    <br />
                    <span className="break-all font-mono text-xs">{video}</span>
                  </div>
                </div>
              </div>
              <DialogDescription className="text-sm leading-5">
                {last ? (
                  <>
                    {video} is the last video in this incident, so{' '}
                    <strong className="text-foreground">the incident is deleted with it</strong>. This permanently deletes the video from
                    storage and{' '}
                    {versionCount === null ? 'all its versions' : <strong className="text-foreground">{allVersions(versionCount)}</strong>}
                    {includingOfficial(hasOfficial)}, with their evidence images. Its link stops working. It cannot be undone.
                  </>
                ) : (
                  <>
                    This permanently deletes the video from storage, its analysis and its evidence images. Incident #{incidentId} keeps its{' '}
                    {otherVideos(videoCount - 1)}
                    {versionCount === null ? '' : ` and ${allVersions(versionCount)}`}, which will say &quot;Includes a removed video:{' '}
                    {video}&quot;. It cannot be undone.
                  </>
                )}
              </DialogDescription>
            </DialogHeader>
            <div className="flex items-start gap-2">
              <Checkbox
                checked={confirmed}
                className="mt-0.5 data-[state=checked]:border-destructive data-[state=checked]:bg-destructive"
                id="confirm-delete-video"
                onCheckedChange={(checked) => setConfirmed(checked === true)}
              />
              <Label className="cursor-pointer text-sm font-normal" htmlFor="confirm-delete-video">
                I understand this cannot be undone.
              </Label>
            </div>
            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
            <DialogFooter className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button
                onClick={() => {
                  setStep({ name: 'choose' });
                  setConfirmed(false);
                  setError(null);
                }}
                type="button"
                variant="outline"
              >
                Back
              </Button>
              <Button disabled={!confirmed} onClick={() => void runDelete()} type="button" variant="destructive">
                {last ? 'Delete video and incident' : 'Delete video'}
              </Button>
            </DialogFooter>
          </>
        )}

        {step.name === 'working' && (
          <>
            <DialogHeader className="gap-2 pr-8">
              <DialogTitle>{video}</DialogTitle>
              <DialogDescription>{step.label}…</DialogDescription>
            </DialogHeader>
            <Progress aria-label={step.label} value={step.percent} />
          </>
        )}

        {step.name === 'moved' && (
          <>
            <DialogHeader className="gap-2 pr-8">
              <DialogTitle className="break-all">
                {video} moved to Incident #{step.newIncidentId}
              </DialogTitle>
              <DialogDescription>
                {step.reportError ? 'The video moved, but its first report could not be built.' : 'Its first report is ready.'}{' '}
                {staleReportNote(incidentId)}
              </DialogDescription>
            </DialogHeader>
            {step.reportError && (
              <Alert variant="destructive">
                <AlertDescription>{step.reportError} Open the incident and press Regenerate to try again.</AlertDescription>
              </Alert>
            )}
            <DialogFooter className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
              <Button onClick={() => change(false)} type="button" variant="outline">
                Stay here
              </Button>
              <Button asChild>
                <Link data-testid="open-new-incident" href={incidentHref(step.newIncidentId)}>
                  Open Incident #{step.newIncidentId}
                </Link>
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
