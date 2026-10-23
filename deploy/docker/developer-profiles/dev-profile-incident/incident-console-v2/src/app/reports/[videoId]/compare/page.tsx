// SPDX-License-Identifier: Apache-2.0
import { AppHeader } from '@/sections/shell/components/AppHeader';
import { RunComparison } from '@/sections/reports/components/RunComparison';
export default async function ComparePage({ params, searchParams }: { params: Promise<{ videoId: string }>; searchParams: Promise<{ left?: string; right?: string }> }) { const [{ videoId }, query] = await Promise.all([params, searchParams]); return <main className="min-h-screen bg-canvas text-ink"><AppHeader active="library" subtitle="Version comparison" /><RunComparison left={query.left || ''} right={query.right || ''} videoId={videoId} /></main>; }
