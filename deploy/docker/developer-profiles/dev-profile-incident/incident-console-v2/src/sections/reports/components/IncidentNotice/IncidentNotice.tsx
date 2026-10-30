// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { cn } from 'cn';

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { incidentNotices, type NoticeScope } from '@/lib/reports/incident-notices';
import { useIncidentNotice } from '@/sections/reports/use-incident-notice';

/**
 * The inline notice for a decision made on this scope (accept, reject, merge, delete, move). It stays until it is
 * dismissed or a version is built. `fromIncidentId` hides the link to the kept incident on that incident's own page.
 */
export function IncidentNotice({
  scope,
  fromIncidentId,
  flush = false,
  className,
}: {
  scope: NoticeScope;
  fromIncidentId?: number;
  /** Edge to edge, as a band on the report page. */
  flush?: boolean;
  className?: string;
}) {
  const notice = useIncidentNotice(scope);
  if (!notice) return null;
  const link = notice.keptIncidentId !== undefined && notice.keptIncidentId !== fromIncidentId ? notice.keptIncidentId : null;
  return (
    <Alert
      className={cn(flush && 'rounded-none border-x-0 border-t-0 px-5 py-2 sm:px-8', className)}
      data-testid="suggestion-notice"
      role="status"
    >
      <AlertTitle>{notice.title}</AlertTitle>
      <AlertDescription className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="min-w-0">
          {notice.detail}
          {link !== null && (
            <>
              {' '}
              <Link className="font-semibold text-primary hover:underline" href={`/reports/${link}`}>
                Open incident {link}
              </Link>
            </>
          )}
        </span>
        <Button
          className="ml-auto"
          data-testid="notice-dismiss"
          onClick={() => incidentNotices.clear(scope)}
          size="xs"
          type="button"
          variant="ghost"
        >
          Dismiss
        </Button>
      </AlertDescription>
    </Alert>
  );
}
