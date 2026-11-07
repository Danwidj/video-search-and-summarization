// SPDX-License-Identifier: Apache-2.0
'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Bar, BarChart, Cell, LabelList, Pie, PieChart, XAxis, YAxis } from 'recharts';
import type { DateRange } from 'react-day-picker';
import { CalendarIcon, ChartColumnIcon, HistoryIcon } from 'lucide-react';
import type { DashboardAnalytics } from '@/modules/dashboard/domain/types';
import { href, type Filters, type LinkFilters, type Range } from '@/modules/dashboard/domain/links';
import {
  allSplit,
  assetRows,
  type BarRow,
  customWindow,
  dashboardView,
  entityTypeRows,
  evidenceRows,
  formatCalendarDay,
  instrumentRows,
  revisedReports,
  SEVERITY_LABELS,
  severityRows,
  type SplitRow,
  typeRows,
  unratedReports,
} from '@/modules/dashboard/domain/charts';
import { getViewerTimeZone } from '@/lib/time';
import { severityChartColor } from '@/lib/ui/severity';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from '@/components/ui/chart';
import { cn } from 'cn';
import { jumpToChartRequest } from '@/sections/dashboard/chart-request-jump';
import { ChartRequest } from '@/sections/dashboard/components/ChartRequest';

const NONE: Filters = { type: '', severity: '', day: '', hour: '' };
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const splitConfig = {
  official: { label: 'Official', color: 'var(--chart-1)' },
  notOfficial: { label: 'Not yet official', color: 'var(--chart-3)' },
} satisfies ChartConfig;

const totalConfig = {
  total: { label: 'Reports', color: 'var(--muted-foreground)' },
} satisfies ChartConfig;

const severityConfig = {
  high: { label: SEVERITY_LABELS.high, color: severityChartColor.high },
  medium: { label: SEVERITY_LABELS.medium, color: severityChartColor.medium },
  low: { label: SEVERITY_LABELS.low, color: severityChartColor.low },
} satisfies ChartConfig;

export function Dashboard() {
  const [data, setData] = useState<DashboardAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  // days is a preset ('7', '30', 'all') or 'custom', the calendar range in custom (applied, never a draft).
  const [days, setDays] = useState('30');
  const [custom, setCustom] = useState<DateRange | undefined>(undefined);
  const [draft, setDraft] = useState<DateRange | undefined>(undefined);
  const [pickerOpen, setPickerOpen] = useState(false);
  const pickerFromSelect = useRef(false);
  const [filters, setFilters] = useState<Filters>(NONE);
  const [error, setError] = useState('');
  const [timeZone, setTimeZone] = useState('UTC');
  // The period window and client timezone depend on the browser, so they are initialized after mount (hydration safe).
  const [range, setRange] = useState<Range | undefined>(undefined);
  useEffect(() => {
    setTimeZone(getViewerTimeZone());
  }, []);
  useEffect(() => {
    if (days === 'all') {
      setRange(null);
      return;
    }
    if (days === 'custom') {
      if (custom?.from) setRange(customWindow(custom));
      return;
    }
    const end = new Date();
    setRange({
      after: new Date(end.getTime() - Number(days) * 86_400_000).toISOString().replace('Z', ''),
      before: end.toISOString().replace('Z', ''),
    });
  }, [days, custom]);
  const openPicker = () => {
    setDraft(custom);
    setPickerOpen(true);
  };
  const applyRange = () => {
    if (!draft?.from) return;
    setCustom({ from: draft.from, to: draft.to ?? draft.from });
    setDays('custom');
    setPickerOpen(false);
  };
  const startOfToday = (() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), now.getDate());
  })();
  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt re-runs the fetch for Try again.
  useEffect(() => {
    if (range === undefined) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ days, timezone: timeZone });
    if (range) {
      params.set('after', range.after);
      params.set('before', range.before);
    }
    Object.entries(filters).forEach(([k, v]) => {
      if (v) params.set(k, v);
    });
    setError('');
    setLoading(true);
    fetch(`/api/dashboard?${params}`, { cache: 'no-store', signal: controller.signal })
      .then(async (r) => {
        const p = (await r.json()) as { analytics?: DashboardAnalytics; error?: string };
        if (!r.ok || !p.analytics) throw new Error(p.error || 'Could not load dashboard');
        setData(p.analytics);
      })
      .catch((e: Error) => {
        if (e.name !== 'AbortError') setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [attempt, days, filters, range, timeZone]);
  const view = dashboardView(data, error);
  const active = Object.values(filters).some(Boolean);
  const toggle = (key: keyof Filters, value: string) => setFilters((f) => ({ ...f, [key]: f[key] === value ? '' : value }));
  const link = (extra: LinkFilters = {}) => href({ ...filters, ...extra }, range ?? null);
  const emptyText = active ? 'No reports match these filters.' : days === 'all' ? 'No reports yet.' : 'No reports in this period.';
  const panel = (content: (d: DashboardAnalytics) => ReactNode, skeletonHeight: string) =>
    data ? content(data) : <Skeleton className={cn('w-full rounded-xl', skeletonHeight)} />;
  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-20 pt-8 sm:px-6 lg:px-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-xs uppercase tracking-[.2em] text-moss">All incidents</p>
          <h1 className="mt-2 text-4xl font-semibold sm:text-5xl">Operations dashboard</h1>
          <p className="mt-3 max-w-3xl text-sm text-ink/50">
            Each video counts once, through its official report, else its newest report. A report stays not yet official until a reviewer
            marks it. Totals, types and assets open the matching reports; severity and the heatmap filter this page.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-4">
          <Button
            className="border-ink/10 bg-white font-normal text-ink"
            onClick={() => jumpToChartRequest(document, window)}
            variant="outline"
          >
            <ChartColumnIcon data-icon="inline-start" />
            Ask for a chart
          </Button>
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={days}
              onOpenChange={(open) => {
                if (open) {
                  pickerFromSelect.current = false;
                  return;
                }
                if (pickerFromSelect.current) openPicker();
              }}
              onValueChange={(val) => {
                if (val !== 'custom') setDays(val);
              }}
            >
              <SelectTrigger className="w-[140px] border-ink/10 bg-white text-ink">
                <SelectValue placeholder="Select period" />
              </SelectTrigger>
              <SelectContent
                onCloseAutoFocus={(event) => {
                  if (!pickerFromSelect.current) return;
                  pickerFromSelect.current = false;
                  event.preventDefault();
                }}
              >
                <SelectItem value="7">Last 7 days</SelectItem>
                <SelectItem value="30">Last 30 days</SelectItem>
                <SelectItem value="all">All time</SelectItem>
                <SelectItem
                  onClick={(event) => {
                    if (!event.defaultPrevented) pickerFromSelect.current = true;
                  }}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter' || event.key === ' ') pickerFromSelect.current = true;
                  }}
                  onPointerUp={(event) => {
                    if (event.pointerType === 'mouse' && !event.defaultPrevented) pickerFromSelect.current = true;
                  }}
                  value="custom"
                >
                  Custom range
                </SelectItem>
              </SelectContent>
            </Select>
            <Popover onOpenChange={(open) => (open ? openPicker() : setPickerOpen(false))} open={pickerOpen}>
              <PopoverTrigger asChild>
                <Button className="border-ink/10 bg-white font-normal text-ink" variant="outline">
                  <CalendarIcon data-icon="inline-start" />
                  {days === 'custom' && custom?.from
                    ? `${formatCalendarDay(custom.from)} – ${formatCalendarDay(custom.to ?? custom.from)}`
                    : 'Choose dates'}
                </Button>
              </PopoverTrigger>
              <PopoverContent align="end" className="w-auto p-3">
                <Calendar
                  defaultMonth={draft?.from ?? custom?.from ?? startOfToday}
                  disabled={{ after: startOfToday }}
                  mode="range"
                  numberOfMonths={1}
                  onSelect={setDraft}
                  selected={draft}
                />
                <div className="flex justify-end gap-2 border-t border-ink/10 pt-3">
                  <Button onClick={() => setPickerOpen(false)} size="sm" variant="outline">
                    Cancel
                  </Button>
                  <Button disabled={!draft?.from} onClick={applyRange} size="sm">
                    Apply
                  </Button>
                </div>
              </PopoverContent>
            </Popover>
          </div>
        </div>
      </div>
      {active && (
        <div className="mt-5 flex flex-wrap items-center gap-2 rounded-2xl border border-moss/20 bg-white p-4 text-sm">
          <strong className="text-moss">Dashboard filters active</strong>
          <span className="text-ink/50">·</span>
          {[
            filters.type && `Type: ${filters.type}`,
            filters.severity && `Severity: ${filters.severity}`,
            filters.day && `Day: ${DAYS[+filters.day]}`,
            filters.hour && `Hour: ${filters.hour}:00 ${timeZone}`,
          ]
            .filter(Boolean)
            .map((filterText) => (
              <Badge key={filterText as string} variant="secondary" className="font-normal text-ink">
                {filterText}
              </Badge>
            ))}
        </div>
      )}
      {active && (
        <Button className="fixed right-6 bottom-6 z-40 shadow-lg" onClick={() => setFilters(NONE)} size="lg">
          Reset filters
        </Button>
      )}
      {error && (
        <Alert variant="destructive" className="mt-6">
          <AlertTitle>{view === 'failed' ? 'Error loading dashboard' : 'Could not refresh the dashboard'}</AlertTitle>
          <AlertDescription>{view === 'failed' ? error : `${error} These are the last figures that loaded.`}</AlertDescription>
          <AlertAction>
            <Button variant="outline" size="sm" onClick={() => setAttempt((n) => n + 1)}>
              Try again
            </Button>
          </AlertAction>
        </Alert>
      )}
      {view !== 'failed' && (
        <div
          aria-busy={loading}
          className={cn('mt-6 grid min-w-0 gap-6 lg:grid-cols-2 xl:grid-cols-12', loading && data && 'opacity-60 transition-opacity')}
          data-testid="dashboard-charts"
        >
          <Panel
            className="lg:col-span-2 xl:col-span-4"
            title="Total reports"
            subtitle="Every version of the reports in the selected period, AI and human"
          >
            {panel(
              (d) => (
                <Total data={d} link={link} />
              ),
              'h-48',
            )}
          </Panel>
          <Panel
            className="lg:col-span-2 xl:col-span-8"
            compact
            title="Activity by day and hour"
            subtitle={`Report time (${timeZone}); select a cell to filter this page`}
          >
            {panel(
              (d) => (
                <Heatmap
                  data={d.heatmap}
                  emptyText={emptyText}
                  onSelect={(day, hour) =>
                    setFilters((f) =>
                      f.day === String(day) && f.hour === String(hour)
                        ? { ...f, day: '', hour: '' }
                        : { ...f, day: String(day), hour: String(hour) },
                    )
                  }
                  selected={`${filters.day}-${filters.hour}`}
                  timeZone={timeZone}
                />
              ),
              'h-56',
            )}
          </Panel>
          <Panel className="xl:col-span-4" title="Incidents by type" subtitle="Open a type for its reports">
            {panel(
              (d) => (
                <SplitBars emptyText={emptyText} hrefFor={(row) => link({ type: row.key })} rows={typeRows(d)} />
              ),
              'h-40',
            )}
          </Panel>
          <Panel className="xl:col-span-4" title="Severity breakdown" subtitle="Select a band to filter this page">
            {panel(
              (d) => (
                <SeverityDonut
                  emptyText={emptyText}
                  onSelect={(row) => toggle('severity', row.key)}
                  rows={severityRows(d)}
                  selected={filters.severity}
                  unrated={unratedReports(d)}
                />
              ),
              'h-48',
            )}
          </Panel>
          <Panel
            className="lg:col-span-2 xl:col-span-4"
            title="Evidence by kind"
            subtitle="Entities, instruments and assets in the counted reports"
          >
            {panel(
              (d) => (
                <EvidenceBars emptyText={emptyText} rows={evidenceRows(d)} />
              ),
              'h-40',
            )}
          </Panel>
          <Panel className="xl:col-span-4" title="Top assets" subtitle="Reports per asset (exact name)">
            {panel(
              (d) => (
                <SplitBars emptyText={emptyText} hrefFor={(row) => link({ asset: row.key })} rows={assetRows(d)} />
              ),
              'h-40',
            )}
          </Panel>
          <Panel className="xl:col-span-4" title="Top instruments" subtitle="Reports per instrument (exact name)">
            {panel(
              (d) => (
                <SplitBars emptyText={emptyText} rows={instrumentRows(d)} />
              ),
              'h-40',
            )}
          </Panel>
          <Panel className="lg:col-span-2 xl:col-span-4" title="Entity types" subtitle="Reports per entity type">
            {panel(
              (d) => (
                <SplitBars emptyText={emptyText} rows={entityTypeRows(d)} />
              ),
              'h-40',
            )}
          </Panel>
        </div>
      )}
      <ChartRequest />
    </div>
  );
}

function Panel({
  title,
  subtitle,
  className,
  compact,
  children,
}: {
  title: string;
  subtitle: string;
  className?: string;
  compact?: boolean;
  children: ReactNode;
}) {
  return (
    <Card className={cn('min-w-0 rounded-3xl border-ink/10 bg-white p-6 shadow-none', compact && 'gap-2', className)}>
      <CardHeader className="gap-1 p-0">
        <CardTitle className="text-lg font-semibold text-ink">{title}</CardTitle>
        <CardDescription className="text-xs text-ink-caption">{subtitle}</CardDescription>
      </CardHeader>
      <CardContent className={cn('min-w-0 p-0', compact ? 'mt-1' : 'mt-5')}>{children}</CardContent>
    </Card>
  );
}

function NoData({ text }: { text: string }) {
  return (
    <Empty className="p-6">
      <EmptyHeader>
        <EmptyTitle>Nothing to show</EmptyTitle>
        <EmptyDescription>{text}</EmptyDescription>
      </EmptyHeader>
    </Empty>
  );
}

function Total({ data, link }: { data: DashboardAnalytics; link: (extra?: LinkFilters) => string }) {
  const { versions } = data;
  const parts = versions
    ? ([
        { key: 'ai', label: 'AI', value: versions.ai, swatch: 'bg-chart-1' },
        { key: 'human', label: 'Human', value: versions.human, swatch: 'bg-chart-3' },
      ] as const)
    : [];
  const total = versions?.total ?? data.total;
  const revised = revisedReports(data);
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link className="text-5xl font-semibold text-ink hover:underline" href={link()}>
          {total}
        </Link>
        {revised !== null && <RevisedChip count={revised} />}
      </div>
      {versions && (
        <>
          <div aria-hidden="true" className="flex h-2 gap-0.5 overflow-hidden rounded-full bg-ink/8">
            {parts.map(({ key, value, swatch }) => (
              <div className={swatch} key={key} style={{ width: `${total ? (value / total) * 100 : 0}%` }} />
            ))}
          </div>
          <dl className="grid grid-cols-2 gap-3">
            {parts.map(({ key, label, value, swatch }) => (
              <div key={key}>
                <dt className="flex items-center gap-1.5 text-xs text-ink/60">
                  <span aria-hidden="true" className={cn('size-2 rounded-xs', swatch)} />
                  {label}
                </dt>
                <dd className="text-2xl font-semibold text-ink tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      <p className="text-xs text-ink-caption">
        {data.total} {data.total === 1 ? 'incident' : 'incidents'}, one per video
      </p>
      <p className="text-xs text-ink-caption">
        All time: {data.videos.uploaded} videos uploaded, {data.videos.withoutReport} without a report.
      </p>
    </div>
  );
}

/** Neutral chip beside the total: how many counted reports have several versions. Its tooltip is also its accessible label. */
function RevisedChip({ count }: { count: number }) {
  const explanation = `${count} of these reports ${count === 1 ? 'has' : 'have'} 2+ versions (edited or re-analysed)`;
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            aria-label={`${count} revised: ${explanation}`}
            className="inline-flex items-center gap-1.5 rounded-full border border-ink/10 bg-ink/5 px-2.5 py-1 text-xs font-semibold text-ink tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ink/40"
            type="button"
          >
            <HistoryIcon aria-hidden="true" className="size-3.5 shrink-0" />
            {count} revised
          </button>
        </TooltipTrigger>
        <TooltipContent>{explanation}</TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

const MAX_TICK_LENGTH = 18;

function RowTick({ x = 0, y = 0, row, href: url }: { x?: number; y?: number; row: BarRow; href?: string }) {
  const shown = row.label.length > MAX_TICK_LENGTH ? `${row.label.slice(0, MAX_TICK_LENGTH - 1)}…` : row.label;
  const label = (
    <text className="fill-ink text-xs capitalize" dy={4} textAnchor="end" x={x} y={y}>
      <title>{row.label}</title>
      {shown}
    </text>
  );
  if (!url) return label;
  return (
    <Link aria-label={`${row.label}: ${row.total} reports`} className="hover:underline" href={url}>
      {label}
    </Link>
  );
}

const ROW_HEIGHT = 40;
const LEGEND_HEIGHT = 36;
const LABEL_ANCHOR = 1e-6;

/** Evidence by kind, or its not-loaded state when the RPC does not return it yet. */
function EvidenceBars({ rows, emptyText }: { rows: SplitRow[] | null; emptyText: string }) {
  if (!rows) return <NoData text="Evidence counts are not available yet." />;
  return <SplitBars emptyText={emptyText} rows={rows} />;
}

/**
 * Rows of official and not-yet-official bars, or of totals alone when a row has no split. With hrefFor, each row opens its
 * reports; without it, the rows are read only.
 */
function SplitBars({ rows, emptyText, hrefFor }: { rows: BarRow[]; emptyText: string; hrefFor?: (row: BarRow) => string }) {
  const router = useRouter();
  if (!rows.length) return <NoData text={emptyText} />;
  const byLabel = new Map(rows.map((row) => [row.label, row]));
  const activate = (index: number) => {
    const row = rows[index];
    if (row && hrefFor) router.push(hrefFor(row));
  };
  const split = allSplit(rows);
  return (
    <ChartContainer
      config={split ? splitConfig : totalConfig}
      className="aspect-auto w-full"
      style={{ height: rows.length * ROW_HEIGHT + (split ? LEGEND_HEIGHT : 0) }}
    >
      <BarChart accessibilityLayer barCategoryGap="30%" data={rows} layout="vertical" margin={{ top: 0, right: 28, left: 0, bottom: 0 }}>
        {/* Headroom past the longest bar, so its total label is not clipped at the chart's edge. */}
        <XAxis allowDecimals={false} domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.12)]} hide type="number" />
        <YAxis
          axisLine={false}
          dataKey="label"
          tick={(props) => {
            const row = byLabel.get(String(props.payload?.value));
            if (!row) return <g />;
            return <RowTick href={hrefFor?.(row)} row={row} x={Number(props.x)} y={Number(props.y)} />;
          }}
          tickLine={false}
          type="category"
          width={132}
        />
        <ChartTooltip content={<ChartTooltipContent />} cursor={false} />
        {split ? (
          <>
            <ChartLegend content={<ChartLegendContent />} itemSorter={null} />
            <Bar
              className={hrefFor ? 'cursor-pointer' : undefined}
              dataKey="official"
              fill="var(--color-official)"
              onClick={(_entry, index) => activate(index)}
              isAnimationActive={false}
              stackId="split"
            />
            <Bar
              className={hrefFor ? 'cursor-pointer' : undefined}
              dataKey="notOfficial"
              fill="var(--color-notOfficial)"
              isAnimationActive={false}
              onClick={(_entry, index) => activate(index)}
              radius={[0, 4, 4, 0]}
              stackId="split"
            />
          </>
        ) : (
          <Bar
            className={hrefFor ? 'cursor-pointer' : undefined}
            dataKey="total"
            fill="var(--color-total)"
            isAnimationActive={false}
            onClick={(_entry, index) => activate(index)}
            radius={[0, 4, 4, 0]}
            stackId="split"
          />
        )}
        {/* Recharts drops a label on a zero-width bar, so the total hangs off a sliver at the end of the stack. */}
        <Bar dataKey={() => LABEL_ANCHOR} fill="transparent" isAnimationActive={false} legendType="none" stackId="split" tooltipType="none">
          <LabelList className="fill-ink font-semibold" dataKey="total" fontSize={12} offset={8} position="right" />
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}

/**
 * Severity bands as a donut, with each band's exact official and not-yet-official counts beside it. The list is the
 * accessible control: each band is a button that filters the page, so no slice has to be hit by a pointer.
 */
function SeverityDonut({
  rows,
  emptyText,
  selected,
  onSelect,
  unrated,
}: {
  rows: SplitRow[];
  emptyText: string;
  selected: string;
  onSelect: (row: SplitRow) => void;
  unrated: number;
}) {
  const rated = rows.reduce((sum, row) => sum + row.total, 0);
  if (!rated) return <NoData text={unrated ? 'These reports have no severity.' : emptyText} />;
  const summary = rows.map((row) => `${row.label} ${row.total}`).join(', ');
  return (
    <div className="flex flex-col gap-5 sm:flex-row sm:items-center xl:flex-col">
      <div aria-label={`Severity of ${rated} rated reports: ${summary}`} className="relative mx-auto size-40 shrink-0" role="img">
        <ChartContainer config={severityConfig} className="aspect-square size-full">
          <PieChart>
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Pie
              cursor="default"
              data={rows}
              dataKey="total"
              innerRadius="62%"
              isAnimationActive={false}
              nameKey="key"
              outerRadius="96%"
              stroke="var(--card)"
              strokeWidth={2}
            >
              {rows.map((row) => (
                <Cell fill={severityChartColor[row.key as keyof typeof severityChartColor]} key={row.key} />
              ))}
            </Pie>
          </PieChart>
        </ChartContainer>
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-semibold text-ink">{rated}</span>
          <span className="text-xs text-ink-caption">{unrated ? 'rated' : 'reports'}</span>
        </div>
      </div>
      <ul className="grid min-w-0 flex-1 gap-1">
        {rows.map((row) => {
          const pressed = selected === row.key;
          return (
            <li key={row.key}>
              <button
                aria-pressed={pressed}
                className={cn(
                  'flex w-full items-center gap-3 rounded-lg px-2 py-2 text-left transition-colors hover:bg-ink/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  pressed && 'bg-ink/5 ring-1 ring-ink/20',
                )}
                onClick={() => onSelect(row)}
                type="button"
              >
                <span
                  aria-hidden="true"
                  className="size-3 shrink-0 rounded-xs"
                  style={{ background: severityChartColor[row.key as keyof typeof severityChartColor] }}
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-sm font-medium text-ink">{row.label}</span>
                  <span className="block text-xs text-ink-caption">
                    Official {row.official} · Not yet official {row.notOfficial}
                  </span>
                </span>
                <span className="text-lg font-semibold tabular-nums text-ink">{row.total}</span>
              </button>
            </li>
          );
        })}
        {unrated > 0 && <li className="px-2 pt-1 text-xs text-ink-caption">No severity: {unrated}</li>}
      </ul>
    </div>
  );
}

const HOURS_OF_DAY = Array.from({ length: 24 }, (_, h) => h);
const HEATMAP_SERIES = {
  count: { label: 'All', color: 'var(--chart-5)' },
  official: { label: 'Official', color: 'var(--chart-1)' },
  notOfficial: { label: 'Not yet official', color: 'var(--chart-3)' },
} as const;
type HeatmapSeries = keyof typeof HEATMAP_SERIES;

function Heatmap({
  data,
  emptyText,
  selected,
  onSelect,
  timeZone,
}: {
  data: DashboardAnalytics['heatmap'];
  emptyText: string;
  selected: string;
  onSelect: (d: number, h: number) => void;
  timeZone: string;
}) {
  const [series, setSeries] = useState<HeatmapSeries>('count');
  const map = useMemo(() => new Map(data.map((x) => [`${x.day}-${x.hour}`, x])), [data]);
  if (!data.length) return <NoData text={emptyText} />;
  const max = Math.max(1, ...data.map((x) => x[series]));
  return (
    <TooltipProvider delayDuration={100}>
      <ToggleGroup
        aria-label="Reports shown"
        onValueChange={(value) => {
          if (value) setSeries(value as HeatmapSeries);
        }}
        size="sm"
        type="single"
        value={series}
        variant="outline"
      >
        {Object.entries(HEATMAP_SERIES).map(([key, { label }]) => (
          <ToggleGroupItem key={key} value={key}>
            {label}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <div className="overflow-x-auto">
        <div className="min-w-[640px]">
          <div className="grid grid-cols-[32px_repeat(24,1fr)] gap-1 text-[10px] text-ink-caption">
            <span />
            {HOURS_OF_DAY.map((h) => (
              <span key={`label-${h}`}>{h % 6 === 0 ? `${h}:00` : ''}</span>
            ))}
          </div>
          {DAYS.map((name, d) => (
            <div className="mt-1 grid grid-cols-[32px_repeat(24,1fr)] gap-1" key={name}>
              <span className="text-[10px]">{name}</span>
              {HOURS_OF_DAY.map((h) => {
                const cell = map.get(`${d}-${h}`);
                const value = cell?.[series] ?? 0;
                const summary = `${name} ${h}:00 ${timeZone}: ${cell?.count ?? 0} reports, ${cell?.official ?? 0} official, ${cell?.notOfficial ?? 0} not yet official`;
                return (
                  <Tooltip key={`hour-${h}`}>
                    <TooltipTrigger asChild>
                      <button
                        aria-label={summary}
                        className={cn(
                          'h-5 rounded-xs transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          selected === `${d}-${h}` ? 'ring-2 ring-ink' : '',
                        )}
                        onClick={() => onSelect(d, h)}
                        style={{
                          background: `color-mix(in srgb, ${HEATMAP_SERIES[series].color} ${value ? 20 + (value / max) * 80 : 4}%, transparent)`,
                        }}
                        type="button"
                      />
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      <span>{summary}</span>
                    </TooltipContent>
                  </Tooltip>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </TooltipProvider>
  );
}
