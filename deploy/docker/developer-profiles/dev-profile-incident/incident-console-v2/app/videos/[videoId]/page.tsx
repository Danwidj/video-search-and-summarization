// SPDX-License-Identifier: Apache-2.0

import Link from 'next/link';

import { AppHeader } from '@/components/app-header';
import { VideoHistoryScreen } from '@/components/video-history-screen';

export default async function VideoPage({ params }: { params: Promise<{ videoId: string }> }) {
  const { videoId } = await params;
  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="videos" subtitle="Video history" />
      <div className="print-hidden mx-auto max-w-[1500px] px-6 pt-1 lg:px-12"><Link className="text-sm font-semibold text-moss" href="/videos">← All videos</Link></div>
      <VideoHistoryScreen videoId={videoId} />
    </main>
  );
}
