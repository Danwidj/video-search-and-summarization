// SPDX-License-Identifier: Apache-2.0

import { StarIcon } from 'lucide-react';
import { cn } from 'cn';

import { versionLabel } from '@/lib/ui/version-label';

/**
 * The one pill that names a version's type: slate blue for the model, plum for a person, and the theme's green with a star when
 * the version is official (the text still names the type, so colour is never the only cue). Colours are the `version-*` theme tokens.
 */
export function VersionPill({
  kind,
  official = false,
  className,
  ...props
}: { kind: 'ai' | 'human'; official?: boolean } & Omit<React.ComponentProps<'span'>, 'children'>) {
  return (
    <span
      className={cn(
        'inline-flex h-5 w-fit shrink-0 items-center gap-1 rounded-full px-2 text-[11px] font-bold whitespace-nowrap text-white',
        official ? 'bg-version-official' : kind === 'human' ? 'bg-version-human' : 'bg-version-model',
        className,
      )}
      data-kind={kind}
      data-official={official ? 'true' : 'false'}
      {...props}
    >
      {official && <StarIcon aria-hidden className="size-3 fill-current" />}
      {versionLabel(kind, official)}
    </span>
  );
}

/**
 * The marker for a video no one has made official yet: the not-yet-official token (pale teal) with a dark label, the same shape
 * as the version pill, so "not yet official" reads the same here as in the Dashboard legend and charts.
 */
export function NotOfficialPill({ className, ...props }: Omit<React.ComponentProps<'span'>, 'children'>) {
  return (
    <span
      className={cn(
        'inline-flex h-5 w-fit shrink-0 items-center rounded-full bg-not-official px-2 text-[11px] font-bold whitespace-nowrap text-ink',
        className,
      )}
      {...props}
    >
      No official version
    </span>
  );
}
