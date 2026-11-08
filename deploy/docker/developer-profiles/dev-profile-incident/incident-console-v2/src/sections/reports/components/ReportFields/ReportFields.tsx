// SPDX-License-Identifier: Apache-2.0

import { type ReactNode, createContext, useContext } from 'react';

import { cn } from '@/lib/utils';

/**
 * The report template, shared by View and Edit: the card header bar, then the field table. With one column it shows each
 * field's value (View). With two columns it shows the saved version beside the draft (Edit), with a column header row.
 */
export function ReportFields({
  children,
  columns = 1,
  draftLabel = 'Draft',
  notices = null,
  savedLabel = 'Saved',
  title,
}: {
  children: ReactNode;
  columns?: 1 | 2;
  /** The card header bar, the same in View and Edit. */
  title: ReactNode;
  /** Notices shown above the table, inside the card. */
  notices?: ReactNode;
  /** Header over the draft column; only shown with two columns. */
  draftLabel?: ReactNode;
  /** Header over the saved column; only shown with two columns. */
  savedLabel?: ReactNode;
}) {
  return (
    <>
      <div className="flex flex-col gap-1 border-b border-l-4 border-border/70 border-l-primary bg-primary/5 px-4 py-2">
        <span className="text-base font-semibold">{title}</span>
      </div>
      {columns === 2 && (
        <div className={cn('grid gap-x-4 border-b border-border/70 px-4 py-2.5 text-xs', GRID[2])} data-testid="compare-header">
          <span className="min-w-0 font-semibold text-foreground">Field</span>
          <span className="min-w-0 rounded-md bg-muted px-2 py-1 text-center font-semibold italic text-foreground">{savedLabel}</span>
          <span className="min-w-0 rounded-md bg-primary/10 px-2 py-1 text-center font-semibold italic text-foreground">{draftLabel}</span>
        </div>
      )}
      <div className="px-4 pb-3 pt-1">
        {notices}
        <dl className="m-0">
          <ColumnsContext.Provider value={columns}>{children}</ColumnsContext.Provider>
        </dl>
      </div>
    </>
  );
}

const GRID = {
  1: 'sm:grid-cols-[6.5rem_minmax(0,1fr)]',
  2: 'sm:grid-cols-[6.5rem_minmax(0,1fr)_minmax(0,1fr)]',
} as const;

const ColumnsContext = createContext<1 | 2>(1);

/**
 * One report field, in View's style. With two columns, `saved` fills the saved cell and `children` the draft cell.
 */
export function ReportFieldRow({ children, label, saved = null }: { children: ReactNode; label: string; saved?: ReactNode }) {
  const columns = useContext(ColumnsContext);
  return (
    <div className={cn('grid gap-1 border-b border-border py-2 last:border-b-0 sm:gap-x-4', GRID[columns])}>
      <dt className="pt-0.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground">{label}</dt>
      {columns === 2 && <dd className="m-0 min-w-0 border-l border-border/70 pl-4 text-sm leading-snug text-foreground">{saved}</dd>}
      <dd className="m-0 min-w-0 border-l border-border/70 pl-4 text-sm leading-snug text-foreground">{children}</dd>
    </div>
  );
}
