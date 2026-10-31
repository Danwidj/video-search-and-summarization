// SPDX-License-Identifier: Apache-2.0
'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { Area, AreaChart, Bar, BarChart, Cell, CartesianGrid, LabelList, Pie, PieChart, XAxis, YAxis } from 'recharts';
import type { DashboardAnalytics } from '@/modules/dashboard/domain/types';
import { href, type Filters, type LinkFilters, type Range } from '@/modules/dashboard/domain/links';
import {
  assetRows,
  dashboardView,
  delta,
  formatDay,
  SEVERITY_LABELS,
  severityRows,
  type SplitRow,
  typeRows,
} from '@/modules/dashboard/domain/charts';
import { getViewerTimeZone } from '@/lib/time';
import { severityChartColor } from '@/lib/ui/severity';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
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
import { ChartRequest } from '@/sections/dashboard/components/ChartRequest';

const NONE: Filters = { type: '', severity: '', day: '', hour: '' };
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

const splitConfig = {
  official: { label: 'Official', color: 'var(--chart-1)' },
  notOfficial: { label: 'Not yet official', color: 'var(--chart-3)' },
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
  const [days, setDays] = useState('30');
  const [compare, setCompare] = useState(true);
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
    const end = new Date();
    setRange({
      after: new Date(end.getTime() - Number(days) * 86_400_000).toISOString().replace('Z', ''),
      before: end.toISOString().replace('Z', ''),
    });
  }, [days]);
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
          <div className="flex items-center gap-2">
            <Checkbox
              id="compare-period"
              checked={compare}
              disabled={days === 'all'}
              onCheckedChange={(checked) => setCompare(Boolean(checked))}
            />
            <Label htmlFor="compare-period" className="cursor-pointer text-sm font-normal select-none">
              vs. previous period
            </Label>
          </div>
          <Select value={days} onValueChange={(val) => setDays(val)}>
            <SelectTrigger className="w-[140px] border-ink/10 bg-white text-ink">
              <SelectValue placeholder="Select period" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">Last 7 days</SelectItem>
              <SelectItem value="30">Last 30 days</SelectItem>
              <SelectItem value="all">All time</SelectItem>
            </SelectContent>
          </Select>
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
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto font-semibold text-moss hover:bg-moss/10 hover:text-moss"
            onClick={() => setFilters(NONE)}
          >
            Reset
          </Button>
        </div>
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
            subtitle="One per video with a report, in the selected period"
          >
            {panel(
              (d) => (
                <Total change={compare ? delta(d.total, d.previous?.total) : null} data={d} link={link} />
              ),
              'h-48',
            )}
          </Panel>
          <Panel
            className="lg:col-span-2 xl:col-span-8"
            title="Incidents over time"
            subtitle={`Reports per day by report date (${timeZone}), official and not yet official`}
          >
            {panel(
              (d) => (
                <Trend emptyText={emptyText} points={d.trend} />
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
                  rows={d.total ? severityRows(d) : []}
                  selected={filters.severity}
                />
              ),
              'h-48',
            )}
          </Panel>
          <Panel className="lg:col-span-2 xl:col-span-4" title="Top targeted assets" subtitle="Reports per asset (exact name)">
            {panel(
              (d) => (
                <SplitBars emptyText={emptyText} hrefFor={(row) => link({ asset: row.key })} rows={assetRows(d)} />
              ),
              'h-40',
            )}
          </Panel>
          <Panel
            className="lg:col-span-2 xl:col-span-12"
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
        </div>
      )}
      <ChartRequest />
    </div>
  );
}

function Panel({ title, subtitle, className, children }: { title: string; subtitle: string; className?: string; children: ReactNode }) {
  return (
    <Card className={cn('min-w-0 rounded-3xl border-ink/10 bg-white p-6 shadow-none', className)}>
      <CardHeader className="gap-1 p-0">
        <CardTitle className="text-lg font-semibold text-ink">{title}</CardTitle>
        <CardDescription className="text-xs text-ink-caption">{subtitle}</CardDescription>
      </CardHeader>
      <CardContent className="mt-5 min-w-0 p-0">{children}</CardContent>
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

function Total({ data, change, link }: { data: DashboardAnalytics; change: number | null; link: (extra?: LinkFilters) => string }) {
  const parts = [
    { key: 'official', label: 'Official', value: data.official, swatch: 'bg-chart-1' },
    { key: 'not_official', label: 'Not yet official', value: data.notOfficial, swatch: 'bg-chart-3' },
  ] as const;
  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link className="text-5xl font-semibold text-ink hover:underline" href={link()}>
          {data.total}
        </Link>
        {change !== null && (
          <p className="mt-1 text-xs text-ink-caption">
            {change > 0 ? '+' : ''}
            {change}% vs. previous
          </p>
        )}
      </div>
      <div aria-hidden="true" className="flex h-2 gap-0.5 overflow-hidden rounded-full bg-ink/8">
        {parts.map(({ key, value, swatch }) => (
          <div className={swatch} key={key} style={{ width: `${data.total ? (value / data.total) * 100 : 0}%` }} />
        ))}
      </div>
      <dl className="grid grid-cols-2 gap-3">
        {parts.map(({ key, label, value, swatch }) => (
          <div key={key}>
            <dt className="flex items-center gap-1.5 text-xs text-ink/60">
              <span aria-hidden="true" className={cn('size-2 rounded-xs', swatch)} />
              {label}
            </dt>
            <dd>
              <Link className="text-2xl font-semibold text-ink hover:underline" href={link({ scope: key })}>
                {value}
              </Link>
            </dd>
          </div>
        ))}
      </dl>
      <p className="text-xs text-ink-caption">
        All time: {data.videos.uploaded} videos uploaded, {data.videos.withoutReport} without a report.
      </p>
    </div>
  );
}

function Trend({ points, emptyText }: { points: DashboardAnalytics['trend']; emptyText: string }) {
  if (!points.some((x) => x.count)) return <NoData text={emptyText} />;
  return (
    <ChartContainer config={splitConfig} className="aspect-auto h-56 w-full">
      <AreaChart accessibilityLayer data={points} margin={{ top: 8, right: 4, left: 0, bottom: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis axisLine={false} dataKey="date" minTickGap={28} tickFormatter={formatDay} tickLine={false} tickMargin={8} />
        <YAxis allowDecimals={false} axisLine={false} tickLine={false} width={28} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(value) => formatDay(String(value))} />} cursor={false} />
        <ChartLegend content={<ChartLegendContent />} itemSorter={null} />
        <Area
          dataKey="official"
          fill="var(--color-official)"
          fillOpacity={0.35}
          isAnimationActive={false}
          stackId="split"
          stroke="var(--color-official)"
          strokeWidth={2}
          type="monotone"
        />
        <Area
          dataKey="notOfficial"
          fill="var(--color-notOfficial)"
          fillOpacity={0.35}
          isAnimationActive={false}
          stackId="split"
          stroke="var(--color-notOfficial)"
          strokeWidth={2}
          type="monotone"
        />
      </AreaChart>
    </ChartContainer>
  );
}

const MAX_TICK_LENGTH = 18;

function RowTick({ x = 0, y = 0, row, href: url }: { x?: number; y?: number; row: SplitRow; href: string }) {
  const shown = row.label.length > MAX_TICK_LENGTH ? `${row.label.slice(0, MAX_TICK_LENGTH - 1)}…` : row.label;
  return (
    <Link aria-label={`${row.label}: ${row.total} reports`} className="hover:underline" href={url}>
      <text className="fill-ink text-xs capitalize" dy={4} textAnchor="end" x={x} y={y}>
        <title>{row.label}</title>
        {shown}
      </text>
    </Link>
  );
}

const ROW_HEIGHT = 40;
const LEGEND_HEIGHT = 36;
const LABEL_ANCHOR = 1e-6;

/** Rows of official and not-yet-official bars. Each row opens its reports. */
function SplitBars({ rows, emptyText, hrefFor }: { rows: SplitRow[]; emptyText: string; hrefFor: (row: SplitRow) => string }) {
  const router = useRouter();
  if (!rows.length) return <NoData text={emptyText} />;
  const byLabel = new Map(rows.map((row) => [row.label, row]));
  const activate = (index: number) => {
    const row = rows[index];
    if (row) router.push(hrefFor(row));
  };
  return (
    <ChartContainer config={splitConfig} className="aspect-auto w-full" style={{ height: rows.length * ROW_HEIGHT + LEGEND_HEIGHT }}>
      <BarChart accessibilityLayer barCategoryGap="30%" data={rows} layout="vertical" margin={{ top: 0, right: 28, left: 0, bottom: 0 }}>
        <XAxis allowDecimals={false} domain={[0, 'dataMax']} hide type="number" />
        <YAxis
          axisLine={false}
          dataKey="label"
          tick={(props) => {
            const row = byLabel.get(String(props.payload?.value));
            if (!row) return <g />;
            return <RowTick href={hrefFor(row)} row={row} x={Number(props.x)} y={Number(props.y)} />;
          }}
          tickLine={false}
          type="category"
          width={132}
        />
        <ChartTooltip content={<ChartTooltipContent />} cursor={false} />
        <ChartLegend content={<ChartLegendContent />} itemSorter={null} />
        <Bar
          className="cursor-pointer"
          dataKey="official"
          fill="var(--color-official)"
          onClick={(_entry, index) => activate(index)}
          isAnimationActive={false}
          stackId="split"
        />
        <Bar
          className="cursor-pointer"
          dataKey="notOfficial"
          fill="var(--color-notOfficial)"
          isAnimationActive={false}
          onClick={(_entry, index) => activate(index)}
          radius={[0, 4, 4, 0]}
          stackId="split"
        />
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
}: {
  rows: SplitRow[];
  emptyText: string;
  selected: string;
  onSelect: (row: SplitRow) => void;
}) {
  if (!rows.length) return <NoData text={emptyText} />;
  const total = rows.reduce((sum, row) => sum + row.total, 0);
  const summary = rows.map((row) => `${row.label} ${row.total}`).join(', ');
  return (
    <div className="flex flex-col gap-5 sm:flex-row sm:items-center xl:flex-col">
      <div aria-label={`Severity of ${total} reports: ${summary}`} className="relative mx-auto size-40 shrink-0" role="img">
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
              stroke="#fff"
              strokeWidth={2}
            >
              {rows.map((row) => (
                <Cell fill={severityChartColor[row.key as keyof typeof severityChartColor]} key={row.key} />
              ))}
            </Pie>
          </PieChart>
        </ChartContainer>
        <div aria-hidden="true" className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-2xl font-semibold text-ink">{total}</span>
          <span className="text-xs text-ink-caption">reports</span>
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
      <div className="mt-4 overflow-x-auto">
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
