// SPDX-License-Identifier: Apache-2.0
import { AppHeader } from '@/components/app-header';
import { RunComparison } from '@/components/run-comparison';
export default async function ComparePage({ params, searchParams }: { params: Promise<{ videoId: string }>; searchParams: Promise<{ left?: string; right?: string }> }) { const [{ videoId }, query] = await Promise.all([params, searchParams]); return <main className="min-h-screen bg-canvas text-ink"><AppHeader active="reports" subtitle="Model comparison" /><RunComparison left={query.left || ''} right={query.right || ''} videoId={videoId} /></main>; }
