// SPDX-License-Identifier: Apache-2.0

'use client';

import Link from 'next/link';

import { CheckIcon, MenuIcon } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { NavigationMenu, NavigationMenuItem, NavigationMenuLink, NavigationMenuList } from '@/components/ui/navigation-menu';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { cn } from 'cn';
import { forgetLibraryState } from '@/lib/library/remembered-state';

const NAV_ITEMS = [
  { href: '/', key: 'analyze', label: 'Analyze' },
  { href: '/library', key: 'library', label: 'Library' },
  { href: '/dashboard', key: 'dashboard', label: 'Dashboard' },
] as const;

/** Where a page may portal its own controls into the bar: left of the brand, and the far right. */
export const HEADER_START_SLOT = 'app-header-start';
export const HEADER_END_SLOT = 'app-header-end';

export function AppHeader({
  active,
  subtitle = 'Video intelligence',
  fullWidth = false,
  workspaceTitle,
}: {
  active?: 'analyze' | 'library' | 'dashboard';
  subtitle?: string;
  /** Edge to edge with small side padding (the report page), instead of the centred max-width container. */
  fullWidth?: boolean;
  /** Replaces the brand with this plain title (the report page: "Report workspace"). */
  workspaceTitle?: string;
}) {
  return (
    <header className="print-hidden relative z-40 shrink-0 border-b border-ink/10 bg-white">
      <div
        className={cn(
          'mx-auto flex min-h-14 w-full items-center justify-between gap-3 px-4 py-2 sm:grid sm:grid-cols-[1fr_auto_1fr] sm:gap-4',
          fullWidth ? 'sm:px-4' : 'max-w-[1500px] sm:px-6 lg:px-12',
        )}
      >
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex items-center gap-3 empty:hidden" id={HEADER_START_SLOT} />
          {workspaceTitle ? (
            <span className="min-w-0 truncate text-lg font-semibold tracking-tight text-ink">{workspaceTitle}</span>
          ) : (
            <Link
              className="flex min-w-0 items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              href="/"
              aria-label="Incident Studio home"
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-full bg-ink text-xs font-bold text-white">IS</span>
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold tracking-tight">Incident Studio</span>
                <span className="block truncate text-[11px] uppercase tracking-[0.2em] text-ink/50">{subtitle}</span>
              </span>
            </Link>
          )}
        </div>
        <NavigationMenu aria-label="Primary navigation" className="hidden flex-none sm:flex" viewport={false}>
          <NavigationMenuList className="gap-0.5 rounded-full border border-ink/10 bg-[#dfe6d6] p-1">
            {NAV_ITEMS.map((item) => (
              <NavigationMenuItem key={item.key}>
                <NavigationMenuLink
                  asChild
                  active={active === item.key}
                  className={cn(
                    'h-8 justify-center rounded-full px-4 py-0 text-sm font-medium transition-colors duration-150',
                    active === item.key
                      ? 'bg-moss font-semibold text-white hover:bg-moss focus:bg-moss data-[active=true]:bg-moss data-[active=true]:text-white data-[active=true]:hover:bg-moss data-[active=true]:focus:bg-moss'
                      : 'text-ink/70 hover:bg-white/60 hover:text-ink focus:bg-white/60 focus:text-ink',
                  )}
                >
                  <Link
                    aria-current={active === item.key ? 'page' : undefined}
                    href={item.href}
                    onClick={item.key === 'library' ? () => forgetLibraryState() : undefined}
                  >
                    {item.label}
                  </Link>
                </NavigationMenuLink>
              </NavigationMenuItem>
            ))}
          </NavigationMenuList>
        </NavigationMenu>
        <div className="flex items-center justify-end gap-2">
          <div className="flex items-center gap-2 empty:hidden" id={HEADER_END_SLOT} />
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
                    className={cn(
                      'flex items-center justify-between gap-3',
                      active === item.key &&
                        'bg-primary font-bold text-primary-foreground focus:bg-primary/90 focus:text-primary-foreground',
                    )}
                    href={item.href}
                    onClick={item.key === 'library' ? () => forgetLibraryState() : undefined}
                  >
                    {item.label}
                    {active === item.key && <CheckIcon aria-hidden="true" className="size-4" />}
                  </Link>
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}
