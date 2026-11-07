// SPDX-License-Identifier: Apache-2.0
'use client';
import { useState } from 'react';
import type { DateRange } from 'react-day-picker';
import { CalendarIcon, InfoIcon, StarIcon, XIcon } from 'lucide-react';
import { formatCalendarDay } from '@/modules/dashboard/domain/charts';
import type { DashboardScope, DashboardSeverity } from '@/modules/dashboard/domain/DashboardRepository';
import { type FilterChip, PERIOD_PRESETS, SCOPE_LABELS } from '@/modules/dashboard/domain/filter-bar';
import { INCIDENT_TYPES } from '@/modules/contract/domain/types';
import { severityVar } from '@/lib/ui/severity';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from 'cn';

const SEVERITIES: { value: DashboardSeverity; label: string }[] = [
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
];
const ALL_TYPES = 'all-types';
const SEGMENT =
  'h-6 rounded-md px-1.5 text-xs font-normal text-ink-caption data-[state=on]:bg-white data-[state=on]:font-semibold data-[state=on]:text-ink data-[state=on]:shadow-xs';
const GROUP = 'gap-0.5 rounded-lg bg-secondary p-0.5';

/** An info icon whose tooltip carries text that used to be a visible sentence. */
export function InfoTip({ label, text, className }: { label: string; text: string; className?: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          aria-label={label}
          className={cn('inline-grid cursor-help place-items-center text-ink-caption hover:text-ink', className)}
          type="button"
        >
          <InfoIcon className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-sm" side="bottom">
        {text}
      </TooltipContent>
    </Tooltip>
  );
}

export function FilterBar({
  about,
  days,
  custom,
  onPeriod,
  onCustom,
  scope,
  onScope,
  severity,
  onSeverity,
  type,
  onType,
  chips,
  onClearChip,
}: {
  about: string;
  days: string;
  custom: DateRange | undefined;
  onPeriod: (days: string) => void;
  onCustom: (range: DateRange) => void;
  scope: DashboardScope;
  onScope: (scope: DashboardScope) => void;
  severity: string;
  onSeverity: (severity: string) => void;
  type: string;
  onType: (type: string) => void;
  chips: FilterChip[];
  onClearChip: (key: FilterChip['key']) => void;
}) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState<DateRange | undefined>(undefined);
  const today = (() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate());
  })();
  return (
    <div
      className="sticky top-0 z-30 border-b border-ink/10 bg-canvas/95 px-4 pt-2 pb-1.5 backdrop-blur sm:px-6 lg:px-12"
      data-testid="dashboard-filter-bar"
    >
      <div className="mx-auto flex max-w-[1500px] flex-nowrap items-center gap-1 overflow-x-auto xl:overflow-visible [&>*]:shrink-0">
        <div className="flex items-center gap-1.5">
          <h1 className="text-base font-bold whitespace-nowrap text-ink">Operations dashboard</h1>
          <InfoTip label="About this dashboard" text={about} />
        </div>
        <span aria-hidden="true" className="mx-0.5 h-5 w-px bg-ink/15" />
        <ToggleGroup
          aria-label="Period"
          className={GROUP}
          onValueChange={(value) => value && onPeriod(value)}
          spacing={0}
          type="single"
          value={days === 'custom' ? '' : days}
        >
          {PERIOD_PRESETS.map(({ value, label, hint }) => (
            <Tooltip key={value}>
              {/* The span takes the tooltip's data-state, so the item keeps the toggle's own on/off state. */}
              <TooltipTrigger asChild>
                <span>
                  <ToggleGroupItem aria-label={hint} className={SEGMENT} value={value}>
                    {label}
                  </ToggleGroupItem>
                </span>
              </TooltipTrigger>
              <TooltipContent side="bottom">{hint}</TooltipContent>
            </Tooltip>
          ))}
        </ToggleGroup>
        <Popover
          onOpenChange={(next) => {
            setOpen(next);
            if (next) setDraft(custom);
          }}
          open={open}
        >
          <PopoverTrigger asChild>
            <Button
              className={cn('h-7 gap-1.5 px-2.5 text-xs font-normal', days === 'custom' && 'border-moss font-semibold text-moss')}
              size="sm"
              variant="outline"
            >
              <CalendarIcon className="size-3.5" />
              {days === 'custom' && custom?.from
                ? `${formatCalendarDay(custom.from)} – ${formatCalendarDay(custom.to ?? custom.from)}`
                : 'Custom'}
            </Button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-auto p-3">
            <Calendar
              defaultMonth={draft?.from ?? custom?.from ?? today}
              disabled={{ after: today }}
              mode="range"
              numberOfMonths={1}
              onSelect={setDraft}
              selected={draft}
            />
            <div className="flex justify-end gap-2 border-t border-ink/10 pt-3">
              <Button onClick={() => setOpen(false)} size="sm" variant="outline">
                Cancel
              </Button>
              <Button
                disabled={!draft?.from}
                onClick={() => {
                  if (!draft?.from) return;
                  onCustom({ from: draft.from, to: draft.to ?? draft.from });
                  setOpen(false);
                }}
                size="sm"
              >
                Apply
              </Button>
            </div>
          </PopoverContent>
        </Popover>
        <span aria-hidden="true" className="mx-0.5 h-5 w-px bg-ink/15" />
        <Tooltip>
          <TooltipTrigger asChild>
            <ToggleGroup
              aria-label="Status"
              className={GROUP}
              onValueChange={(value) => value && onScope(value as DashboardScope)}
              spacing={0}
              type="single"
              value={scope}
            >
              {(Object.keys(SCOPE_LABELS) as DashboardScope[]).map((value) => (
                <ToggleGroupItem className={SEGMENT} key={value} value={value}>
                  {value === 'official' && <StarIcon className="size-3 fill-current text-version-official" />}
                  {SCOPE_LABELS[value]}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </TooltipTrigger>
          <TooltipContent side="bottom">Report status</TooltipContent>
        </Tooltip>
        <Tooltip>
          <TooltipTrigger asChild>
            <ToggleGroup
              aria-label="Severity"
              className={GROUP}
              onValueChange={(value) => onSeverity(value)}
              spacing={0}
              type="single"
              value={severity}
            >
              {SEVERITIES.map(({ value, label }) => (
                <ToggleGroupItem className={SEGMENT} key={value} value={value}>
                  <span aria-hidden="true" className="size-2 rounded-xs" style={{ background: severityVar[value] }} />
                  {label}
                </ToggleGroupItem>
              ))}
            </ToggleGroup>
          </TooltipTrigger>
          <TooltipContent side="bottom">Severity</TooltipContent>
        </Tooltip>
        <Select onValueChange={(value) => onType(value === ALL_TYPES ? '' : value)} value={type || ALL_TYPES}>
          <SelectTrigger aria-label="Incident type" className="h-7 w-[104px] gap-1 px-2 text-xs capitalize" size="sm">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_TYPES}>All types</SelectItem>
            {INCIDENT_TYPES.map((value) => (
              <SelectItem className="capitalize" key={value} value={value}>
                {value}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <span className="min-w-0 flex-1" />
        <span className="flex items-center gap-3 text-xs text-ink-caption">
          <span className="flex items-center gap-1.5">
            <StarIcon aria-hidden="true" className="size-3 fill-current text-version-official" />
            Official
          </span>
          <span className="flex items-center gap-1.5">
            <span aria-hidden="true" className="size-2.5 rounded-xs border border-dashed border-not-official-line bg-not-official" />
            Not yet official
          </span>
        </span>
      </div>
      {chips.length > 0 && (
        <div className="mx-auto flex min-h-[26px] max-w-[1500px] flex-wrap items-center gap-1.5 pt-1.5" data-testid="dashboard-chips">
          {chips.map((chip) => (
            <Badge
              className="h-[22px] gap-1 border border-ink/15 bg-white pr-1 pl-2 text-xs font-normal text-ink"
              key={chip.key}
              variant="outline"
            >
              <span className="text-ink-caption">{chip.label}:</span>
              <b className="font-semibold capitalize">{chip.value}</b>
              <button
                aria-label={`Clear ${chip.label}`}
                className="grid size-4 place-items-center rounded-full text-ink-caption hover:bg-secondary hover:text-ink"
                onClick={() => onClearChip(chip.key)}
                type="button"
              >
                <XIcon className="size-3" />
              </button>
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}
