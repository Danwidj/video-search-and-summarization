// SPDX-License-Identifier: Apache-2.0

import { Suspense } from 'react';

import { AppHeader } from '@/components/app-header';
import { Library } from '@/components/library/library-screen';

export default function LibraryPage() {
  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="library" subtitle="Incident library" />
      <Suspense fallback={null}><Library /></Suspense>
    </main>
  );
}
