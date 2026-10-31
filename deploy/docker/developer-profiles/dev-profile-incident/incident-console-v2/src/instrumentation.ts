// SPDX-License-Identifier: Apache-2.0

// Next.js runs register() once when the server process starts: it starts the
// background analysis loop (lib/jobs/loop.ts) in the Node.js runtime only.
export async function register() {
  if (process.env.NEXT_RUNTIME !== 'nodejs') return;
  const { startAnalysisJobLoop } = await import('@/lib/jobs/loop');
  startAnalysisJobLoop();
}
