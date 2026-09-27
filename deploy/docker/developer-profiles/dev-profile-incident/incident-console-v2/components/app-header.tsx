// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';

import { HealthStrip } from '@/components/health-strip';

export function AppHeader({ active, subtitle = 'Video intelligence' }: { active: 'analyze' | 'reports' | 'dashboard'; subtitle?: string }) {
  return <header className="print-hidden relative z-10 mx-auto flex max-w-[1500px] items-center justify-between gap-4 px-6 py-7 lg:px-12">
    <Link className="flex items-center gap-3" href="/" aria-label="Incident Studio home"><span className="grid h-10 w-10 place-items-center rounded-full bg-ink text-sm font-bold text-white">IS</span><span><span className="block text-sm font-semibold tracking-tight">Incident Studio</span><span className="block text-[11px] uppercase tracking-[0.2em] text-ink/50">{subtitle}</span></span></Link>
    <nav className="flex items-center gap-3 text-xs text-ink/60 sm:gap-6 sm:text-sm" aria-label="Primary navigation">
      <Link className={active === 'analyze' ? 'font-bold text-ink' : 'hover:text-ink'} href="/">Analyze</Link>
      <Link className={active === 'reports' ? 'font-bold text-ink' : 'hover:text-ink'} href="/reports">Reports</Link>
      <Link className={active === 'dashboard' ? 'font-bold text-ink' : 'hover:text-ink'} href="/dashboard">Dashboard</Link>
    </nav>
    <div className="hidden lg:block"><HealthStrip /></div>
  </header>;
}
