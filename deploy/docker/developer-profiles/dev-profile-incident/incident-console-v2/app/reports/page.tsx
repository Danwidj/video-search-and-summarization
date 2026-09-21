// SPDX-License-Identifier: Apache-2.0

import { AppHeader } from '@/components/app-header';
import { ReportsLibrary } from '@/components/reports-library';
import { Suspense } from 'react';

export default function ReportsPage() {
  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="reports" subtitle="Report library" />
      <Suspense fallback={<div className="mx-auto max-w-[1500px] px-6 py-20 text-ink/50">Loading report library…</div>}><ReportsLibrary /></Suspense>
    </main>
  );
}
