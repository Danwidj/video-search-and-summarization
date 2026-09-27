// SPDX-License-Identifier: Apache-2.0

import { AppHeader } from '@/components/app-header';
import { GroundTruthScreen } from '@/components/ground-truth-screen';

export default async function GroundTruthPage({ params, searchParams }: { params: Promise<{ videoId: string }>; searchParams: Promise<{ run?: string }> }) {
  const [{ videoId }, { run }] = await Promise.all([params, searchParams]);
  return (
    <main className="min-h-screen bg-canvas text-ink">
      <AppHeader active="videos" subtitle="Ground truth" />
      <GroundTruthScreen runId={run} videoId={videoId} />
    </main>
  );
}
