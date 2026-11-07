// SPDX-License-Identifier: Apache-2.0
'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { Bar, BarChart, Cell, LabelList, Pie, PieChart, XAxis, YAxis } from 'recharts';
import type { DateRange } from 'react-day-picker';
import { HistoryIcon, RotateCcwIcon } from 'lucide-react';
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
  instrumentRows,
  revisedReports,
  SEVERITY_LABELS,
  severityRows,
  type SplitRow,
  typeRows,
  unratedReports,
} from '@/modules/dashboard/domain/charts';
import type { DashboardScope } from '@/modules/dashboard/domain/DashboardRepository';
import {
  DAY_NAMES,
  DEFAULT_PERIOD,
  DEFAULT_SCOPE,
  filterChips,
  type FilterChip,
  heatmapSeries,
  presetWindow,
} from '@/modules/dashboard/domain/filter-bar';
import { getViewerTimeZone } from '@/lib/time';
import { severityVar } from '@/lib/ui/severity';
import { Button } from '@/components/ui/button';
import { Alert, AlertAction, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { darken, DimSector, PopBar, PopSector } from '@/sections/dashboard/components/Dashboard/chart-hover';
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';
import { cn } from 'cn';
import { formatCalendarDay } from '@/modules/dashboard/domain/charts';
import { jumpToChartRequest } from '@/sections/dashboard/chart-request-jump';
import { ChartRequest } from '@/sections/dashboard/components/ChartRequest';
import { FilterBar, InfoTip } from '@/sections/dashboard/components/FilterBar';

const NONE: Filters = { type: '', severity: '', day: '', hour: '' };
const ABOUT =
  'Each video counts once, through its official report, else its newest report. A report stays not yet official until a reviewer marks it. Totals, types and assets open the matching reports in the Library; severity and the heatmap filter this page.';

const splitConfig = {
  official: { label: 'Official', color: 'var(--color-version-official)' },
  notOfficial: { label: 'Not yet official', color: 'var(--color-not-official)' },
} satisfies ChartConfig;

const totalConfig = {
  total: { label: 'Reports', color: 'var(--muted-foreground)' },
} satisfies ChartConfig;

const severityConfig = {
  high: { label: SEVERITY_LABELS.high, color: severityVar.high },
  medium: { label: SEVERITY_LABELS.medium, color: severityVar.medium },
  low: { label: SEVERITY_LABELS.low, color: severityVar.low },
} satisfies ChartConfig;

export function Dashboard() {
  const [data, setData] = useState<DashboardAnalytics | null>(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  // days is a preset ('7', '30', '90', 'all') or 'custom', the calendar range in custom (applied, never a draft).
  const [days, setDays] = useState(DEFAULT_PERIOD);
  const [custom, setCustom] = useState<DateRange | undefined>(undefined);
  const [scope, setScope] = useState<DashboardScope>(DEFAULT_SCOPE);
  const [filters, setFilters] = useState<Filters>(NONE);
  const [error, setError] = useState('');
  const [timeZone, setTimeZone] = useState('UTC');
  // The period window and client timezone depend on the browser, so they are initialized after mount (hydration safe).
  const [range, setRange] = useState<Range | undefined>(undefined);
  useEffect(() => {
    setTimeZone(getViewerTimeZone());
  }, []);
  useEffect(() => {
    if (days === 'custom') {
      if (custom?.from) setRange(customWindow(custom));
      return;
    }
    setRange(presetWindow(days, new Date()));
  }, [days, custom]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: attempt re-runs the fetch for Try again.
  useEffect(() => {
    if (range === undefined) return;
    const controller = new AbortController();
    const params = new URLSearchParams({ days, timezone: timeZone, scope });
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
  }, [attempt, days, filters, range, scope, timeZone]);
  const view = dashboardView(data, error);
  const customLabel = custom?.from ? `${formatCalendarDay(custom.from)} – ${formatCalendarDay(custom.to ?? custom.from)}` : '';
  const chips = filterChips({ days, customLabel, scope, filters, timeZone });
  const active = chips.length > 0;
  const toggle = (key: keyof Filters, value: string) => setFilters((f) => ({ ...f, [key]: f[key] === value ? '' : value }));
  const clearChip = (key: FilterChip['key']) => {
    if (key === 'period') setDays(DEFAULT_PERIOD);
    else if (key === 'scope') setScope(DEFAULT_SCOPE);
    else if (key === 'cell') setFilters((f) => ({ ...f, day: '', hour: '' }));
    else setFilters((f) => ({ ...f, [key]: '' }));
  };
  const reset = () => {
    setDays(DEFAULT_PERIOD);
    setScope(DEFAULT_SCOPE);
    setFilters(NONE);
  };
  const link = (extra: LinkFilters = {}) => href({ ...filters, scope, ...extra }, range ?? null);
  const emptyText = active ? 'No reports match these filters.' : days === 'all' ? 'No reports yet.' : 'No reports in this period.';
  const panel = (content: (d: DashboardAnalytics) => ReactNode, skeletonHeight: string) =>
    data ? content(data) : <Skeleton className={cn('w-full rounded-xl', skeletonHeight)} />;
  return (
    <TooltipProvider delayDuration={100}>
      <FilterBar
        about={ABOUT}
        chips={chips}
        custom={custom}
        days={days}
        onAsk={() => jumpToChartRequest(document, window)}
        onClearChip={clearChip}
        onCustom={(next) => {
          setCustom(next);
          setDays('custom');
        }}
        onPeriod={setDays}
        onScope={setScope}
        onSeverity={(value) => setFilters((f) => ({ ...f, severity: value }))}
        onType={(value) => setFilters((f) => ({ ...f, type: value }))}
        scope={scope}
        severity={filters.severity}
        type={filters.type}
      />
      <div className="mx-auto max-w-[1500px] px-4 pb-10 pt-2.5 sm:px-6 lg:px-12 lg:pr-[88px]">
        {/* The reset sits in a rail the layout reserves on the right, so it covers no chart. */}
        <Tooltip>
          <TooltipTrigger asChild>
            <span className="fixed right-2.5 bottom-5 z-40">
              <Button
                aria-label="Reset filters"
                className={cn(
                  'relative h-14 w-11 flex-col gap-0.5 rounded-2xl px-0 text-[10px] shadow-lg',
                  active && 'bg-moss text-white hover:bg-moss/90',
                )}
                disabled={!active}
                onClick={reset}
                variant="outline"
              >
                <RotateCcwIcon className="size-4" />
                Reset
                {active && (
                  <span className="absolute -top-1.5 -right-1.5 grid min-w-[18px] place-items-center rounded-full bg-moss px-1 text-[10px] font-bold text-white">
                    {chips.length}
                  </span>
                )}
              </Button>
            </span>
          </TooltipTrigger>
          <TooltipContent side="left">Reset the period and every filter</TooltipContent>
        </Tooltip>
        {error && (
          <Alert variant="destructive" className="mb-2.5">
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
            className={cn('grid min-w-0 gap-2.5 lg:grid-cols-12', loading && data && 'opacity-60 transition-opacity')}
            data-testid="dashboard-charts"
          >
            <Panel
              className="lg:col-span-3"
              title="Total reports"
              subtitle="Every version of the reports in the selected period, AI and human"
            >
              {panel(
                (d) => (
                  <Total data={d} link={link} />
                ),
                'h-32',
              )}
            </Panel>
            <Panel
              className="lg:col-span-6"
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
                    scope={scope}
                    selected={`${filters.day}-${filters.hour}`}
                    timeZone={timeZone}
                  />
                ),
                'h-32',
              )}
            </Panel>
            <Panel className="lg:col-span-3" title="Severity breakdown" subtitle="Select a band to filter this page">
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
                'h-32',
              )}
            </Panel>
            <Panel className="lg:col-span-3" title="Incidents by type" subtitle="Open a type for its reports">
              {panel(
                (d) => (
                  <SplitBars emptyText={emptyText} hrefFor={(row) => link({ type: row.key })} rows={typeRows(d)} />
                ),
                'h-40',
              )}
            </Panel>
            <Panel className="lg:col-span-3" title="Top assets" subtitle="Reports per asset (exact name)">
              {panel(
                (d) => (
                  <SplitBars emptyText={emptyText} hrefFor={(row) => link({ asset: row.key })} rows={assetRows(d)} />
                ),
                'h-40',
              )}
            </Panel>
            <Panel className="lg:col-span-3" title="Top instruments" subtitle="Reports per instrument (exact name)">
              {panel(
                (d) => (
                  <SplitBars emptyText={emptyText} rows={instrumentRows(d)} />
                ),
                'h-40',
              )}
            </Panel>
            <div className="flex min-w-0 flex-col gap-2.5 lg:col-span-3">
              <Panel title="Evidence by kind" subtitle="Entities, instruments and assets in the counted reports">
                {panel(
                  (d) => (
                    <EvidenceBars emptyText={emptyText} rows={evidenceRows(d)} />
                  ),
                  'h-20',
                )}
              </Panel>
              <Panel title="Entity types" subtitle="Reports per entity type">
                {panel(
                  (d) => (
                    <SplitBars emptyText={emptyText} rows={entityTypeRows(d)} />
                  ),
                  'h-20',
                )}
              </Panel>
            </div>
          </div>
        )}
        <ChartRequest />
      </div>
    </TooltipProvider>
  );
}

function Panel({ title, subtitle, className, children }: { title: string; subtitle: string; className?: string; children: ReactNode }) {
  return (
    <Card className={cn('min-w-0 gap-1.5 rounded-[14px] border-ink/10 bg-white px-3.5 py-2.5 shadow-none', className)}>
      <CardHeader className="flex flex-row items-center gap-1.5 p-0">
        <CardTitle className="text-[13px] font-bold text-ink">{title}</CardTitle>
        <InfoTip label={`About ${title}`} text={subtitle} />
      </CardHeader>
      <CardContent className="min-w-0 p-0">{children}</CardContent>
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
        { key: 'ai', label: 'AI', value: versions.ai, swatch: 'bg-version-model' },
        { key: 'human', label: 'Human', value: versions.human, swatch: 'bg-version-human' },
      ] as const)
    : [];
  const total = versions?.total ?? data.total;
  const revised = revisedReports(data);
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <Link className="text-4xl leading-none font-semibold text-ink hover:underline" href={link()}>
          {total}
        </Link>
        {revised !== null && <RevisedChip count={revised} />}
      </div>
      {versions && (
        <>
          <div aria-hidden="true" className="flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-ink/8">
            {parts.map(({ key, value, swatch }) => (
              <div className={swatch} key={key} style={{ width: `${total ? (value / total) * 100 : 0}%` }} />
            ))}
          </div>
          <dl className="grid grid-cols-2 gap-2">
            {parts.map(({ key, label, value, swatch }) => (
              <div key={key}>
                <dt className="flex items-center gap-1.5 text-xs text-ink/60">
                  <span aria-hidden="true" className={cn('size-2 rounded-xs', swatch)} />
                  {label}
                </dt>
                <dd className="text-lg leading-tight font-semibold text-ink tabular-nums">{value}</dd>
              </div>
            ))}
          </dl>
        </>
      )}
      <p className="text-xs text-ink-caption">
        {data.total} {data.total === 1 ? 'incident' : 'incidents'}, one per video. All time: {data.videos.uploaded} videos uploaded,{' '}
        {data.videos.withoutReport} without a report.
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

/** How long every chart takes to draw, on load and on a filter change. */
const CHART_ANIMATION_MS = 1500;

/** Recharts' own start-up animation, eased out, and off when the viewer asks for reduced motion. */
function useChartMotion() {
  const [reduce, setReduce] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches,
  );
  useEffect(() => {
    const query = window.matchMedia('(prefers-reduced-motion: reduce)');
    const sync = () => setReduce(query.matches);
    sync();
    query.addEventListener('change', sync);
    return () => query.removeEventListener('change', sync);
  }, []);
  return { animationDuration: CHART_ANIMATION_MS, animationEasing: 'ease-out' as const, isAnimationActive: !reduce };
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

const ROW_HEIGHT = 28;
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
  const motion = useChartMotion();
  if (!rows.length) return <NoData text={emptyText} />;
  const byLabel = new Map(rows.map((row) => [row.label, row]));
  const activate = (index: number) => {
    const row = rows[index];
    if (row && hrefFor) router.push(hrefFor(row));
  };
  const split = allSplit(rows);
  return (
    <ChartContainer config={split ? splitConfig : totalConfig} className="aspect-auto w-full" style={{ height: rows.length * ROW_HEIGHT }}>
      <BarChart accessibilityLayer barCategoryGap="30%" data={rows} layout="vertical" margin={{ top: 0, right: 28, left: 0, bottom: 0 }}>
        {/* Headroom past the longest bar, so its total label is not clipped at the chart's edge. */}
        <XAxis allowDecimals={false} domain={[0, (dataMax: number) => Math.ceil(dataMax * 1.12)]} hide type="number" />
        <YAxis
          axisLine={false}
          dataKey="label"
          interval={0}
          tick={(props) => {
            const row = byLabel.get(String(props.payload?.value));
            if (!row) return <g />;
            return <RowTick href={hrefFor?.(row)} row={row} x={Number(props.x)} y={Number(props.y)} />;
          }}
          tickLine={false}
          type="category"
          width={112}
        />
        <ChartTooltip content={<ChartTooltipContent />} cursor={false} />
        {split ? (
          <>
            <Bar
              activeBar={PopBar}
              className={hrefFor ? 'cursor-pointer' : undefined}
              dataKey="official"
              fill="var(--color-official)"
              onClick={(_entry, index) => activate(index)}
              {...motion}
              stackId="split"
            />
            <Bar
              activeBar={PopBar}
              className={hrefFor ? 'cursor-pointer' : undefined}
              dataKey="notOfficial"
              fill="var(--color-notOfficial)"
              {...motion}
              onClick={(_entry, index) => activate(index)}
              radius={[0, 4, 4, 0]}
              stackId="split"
            />
          </>
        ) : (
          <Bar
            activeBar={PopBar}
            className={hrefFor ? 'cursor-pointer' : undefined}
            dataKey="total"
            fill="var(--color-total)"
            {...motion}
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
  const motion = useChartMotion();
  const rated = rows.reduce((sum, row) => sum + row.total, 0);
  if (!rated) return <NoData text={unrated ? 'These reports have no severity.' : emptyText} />;
  const summary = rows.map((row) => `${row.label} ${row.total}`).join(', ');
  return (
    <div className="flex flex-row items-center gap-3">
      <div aria-label={`Severity of ${rated} rated reports: ${summary}`} className="relative size-28 shrink-0" role="img">
        <ChartContainer config={severityConfig} className="aspect-square size-full">
          <PieChart>
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Pie
              activeShape={PopSector}
              cursor="default"
              data={rows}
              dataKey="total"
              inactiveShape={DimSector}
              innerRadius="62%"
              {...motion}
              nameKey="key"
              outerRadius="82%"
              stroke="var(--card)"
              strokeWidth={2}
            >
              {rows.map((row) => (
                <Cell fill={severityVar[row.key as keyof typeof severityVar]} key={row.key} />
              ))}
            </Pie>
          </PieChart>
        </ChartContainer>
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-lg font-semibold text-ink">{rated}</span>
          <span className="text-xs text-ink-caption">{unrated ? 'rated' : 'reports'}</span>
        </div>
      </div>
      <ul className="grid min-w-0 flex-1 gap-0.5">
        {rows.map((row) => {
          const pressed = selected === row.key;
          return (
            <li key={row.key}>
              <button
                aria-pressed={pressed}
                className={cn(
                  'flex w-full items-center gap-2 rounded-lg px-1.5 py-1 text-left transition-colors hover:bg-ink/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  pressed && 'bg-ink/5 ring-1 ring-ink/20',
                )}
                onClick={() => onSelect(row)}
                title={`${row.official} official, ${row.notOfficial} not yet official`}
                type="button"
              >
                <span
                  aria-hidden="true"
                  className="size-3 shrink-0 rounded-xs"
                  style={{ background: severityVar[row.key as keyof typeof severityVar] }}
                />
                <span className="min-w-0 flex-1">
                  <span className="block text-xs font-medium text-ink">{row.label}</span>
                </span>
                <span className="text-base font-semibold tabular-nums text-ink">{row.total}</span>
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
const SERIES_COLOR = {
  count: 'var(--chart-5)',
  official: 'var(--color-version-official)',
  notOfficial: 'var(--color-not-official)',
} as const;

function Heatmap({
  data,
  emptyText,
  selected,
  onSelect,
  scope,
  timeZone,
}: {
  data: DashboardAnalytics['heatmap'];
  emptyText: string;
  selected: string;
  onSelect: (d: number, h: number) => void;
  scope: DashboardScope;
  timeZone: string;
}) {
  const series = heatmapSeries(scope);
  const map = useMemo(() => new Map(data.map((x) => [`${x.day}-${x.hour}`, x])), [data]);
  if (!data.length) return <NoData text={emptyText} />;
  const max = Math.max(1, ...data.map((x) => x[series]));
  return (
    <TooltipProvider delayDuration={100}>
      <div className="overflow-x-auto p-2">
        <div className="min-w-[440px]">
          <div className="grid grid-cols-[32px_repeat(24,1fr)] gap-0.5 text-[10px] text-ink-caption">
            <span />
            {HOURS_OF_DAY.map((h) => (
              <span key={`label-${h}`}>{h % 6 === 0 ? `${h}:00` : ''}</span>
            ))}
          </div>
          {DAY_NAMES.map((name, d) => (
            <div className="mt-0.5 grid grid-cols-[32px_repeat(24,1fr)] gap-0.5" key={name}>
              <span className="text-[10px]">{name}</span>
              {HOURS_OF_DAY.map((h) => {
                const cell = map.get(`${d}-${h}`);
                const value = cell?.[series] ?? 0;
                const share = value ? 20 + (value / max) * 80 : 4;
                const summary = `${name} ${h}:00 ${timeZone}: ${cell?.count ?? 0} reports, ${cell?.official ?? 0} official, ${cell?.notOfficial ?? 0} not yet official`;
                return (
                  <Tooltip key={`hour-${h}`}>
                    <TooltipTrigger asChild>
                      <button
                        aria-label={summary}
                        className={cn(
                          'relative h-4 rounded-xs bg-(--cell) transition duration-150 hover:z-10 hover:bg-(--cell-hover) hover:ring-2 hover:ring-ink motion-safe:hover:scale-150 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          selected === `${d}-${h}` ? 'ring-2 ring-ink' : '',
                        )}
                        onClick={() => onSelect(d, h)}
                        style={
                          {
                            '--cell': `color-mix(in srgb, ${SERIES_COLOR[series]} ${share}%, transparent)`,
                            '--cell-hover': darken(`color-mix(in srgb, ${SERIES_COLOR[series]} ${share}%, white)`),
                          } as CSSProperties
                        }
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
