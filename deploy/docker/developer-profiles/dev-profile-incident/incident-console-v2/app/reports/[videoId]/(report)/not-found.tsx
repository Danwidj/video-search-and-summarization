// SPDX-License-Identifier: Apache-2.0

import Link from 'next/link';

import { ReportWorkspace } from '@/components/report-screen';

// getReport found no run, video or incident for the link.
export default function ReportNotFound() {
  return (
    <ReportWorkspace>
      <div className="mx-auto grid min-h-[65vh] max-w-xl place-items-center px-6 text-center">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-clay">Report not found</p>
          <h1 className="mt-3 text-3xl font-semibold">This analysis no longer exists.</h1>
          <p className="mt-4 text-sm leading-6 text-ink/60">The run may have been deleted, or the link names the wrong video or run.</p>
          <Link className="mt-7 inline-block rounded-full bg-ink px-5 py-3 text-sm font-semibold text-white" href="/reports">Back to all reports</Link>
        </div>
      </div>
    </ReportWorkspace>
  );
}
