// SPDX-License-Identifier: Apache-2.0

'use client';

import { ReportUnavailable, ReportWorkspace } from '@/components/report-screen';

// Anything page.tsx does not catch itself; production replaces the message with a generic one.
export default function ReportError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <ReportWorkspace><ReportUnavailable message={error.message || 'Could not load the report'} reset={reset} /></ReportWorkspace>;
}
