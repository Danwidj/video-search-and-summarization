// SPDX-License-Identifier: Apache-2.0

import { Suspense } from 'react';

import { AppHeader } from '@/components/app-header';
import { VideosScreen } from '@/components/videos-screen';

export default function VideosPage() {
  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="videos" subtitle="Video history" />
      <Suspense fallback={null}><VideosScreen /></Suspense>
    </main>
  );
}
