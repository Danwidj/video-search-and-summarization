// SPDX-License-Identifier: Apache-2.0

import { Suspense } from 'react';

import { AppHeader } from '@/sections/shell/components/AppHeader';
import { Library } from '@/sections/library/components/LibraryScreen';

export default function LibraryPage() {
  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="library" subtitle="Incident library" />
      <Suspense fallback={null}><Library /></Suspense>
    </main>
  );
}
