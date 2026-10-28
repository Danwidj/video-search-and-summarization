// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';

import { MenuIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { cn } from 'cn';
import { HealthStrip } from '@/sections/shell/components/HealthStrip';

const NAV_ITEMS = [
  { href: '/', key: 'analyze', label: 'Analyze' },
  { href: '/library', key: 'library', label: 'Library' },
  { href: '/videos', key: 'videos', label: 'Videos' },
  { href: '/dashboard', key: 'dashboard', label: 'Dashboard' },
] as const;

export function AppHeader({
  active,
  subtitle = 'Video intelligence',
}: {
  active: 'analyze' | 'library' | 'videos' | 'dashboard';
  subtitle?: string;
}) {
  return (
    <header className="print-hidden relative z-10 mx-auto flex max-w-[1500px] items-center justify-between gap-3 px-4 py-5 sm:gap-4 sm:px-6 sm:py-7 lg:px-12">
      <Link
        className="flex min-w-0 items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        href="/"
        aria-label="Incident Studio home"
      >
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-ink text-sm font-bold text-white">IS</span>
        <span className="min-w-0">
          <span className="block truncate text-sm font-semibold tracking-tight">Incident Studio</span>
          <span className="block truncate text-[11px] uppercase tracking-[0.2em] text-ink/50">{subtitle}</span>
        </span>
      </Link>
      <nav className="hidden items-center gap-2 sm:flex" aria-label="Primary navigation">
        {NAV_ITEMS.map((item) => (
          <Button
            key={item.key}
            asChild
            variant="ghost"
            size="sm"
            className={cn(
              'px-2.5 py-1 text-xs sm:text-sm font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              active === item.key ? 'font-bold text-ink bg-black/5 hover:bg-black/8' : 'text-ink/60 hover:text-ink',
            )}
          >
            <Link href={item.href}>{item.label}</Link>
          </Button>
        ))}
      </nav>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button aria-label="Open navigation menu" className="shrink-0 sm:hidden" size="icon" variant="outline">
            <MenuIcon aria-hidden="true" />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          {NAV_ITEMS.map((item) => (
            <DropdownMenuItem asChild key={item.key}>
              <Link
                aria-current={active === item.key ? 'page' : undefined}
                className={active === item.key ? 'font-bold' : ''}
                href={item.href}
              >
                {item.label}
              </Link>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>
      <div className="hidden lg:block">
        <HealthStrip />
      </div>
    </header>
  );
}
