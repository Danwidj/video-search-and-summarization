// SPDX-License-Identifier: Apache-2.0
'use client';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import { Bar, BarChart, Cell, LabelList, Pie, PieChart, Treemap, XAxis, YAxis } from 'recharts';
import type { DateRange } from 'react-day-picker';
import { PawPrintIcon, RotateCcwIcon, UserRoundIcon } from 'lucide-react';
import type { DashboardAnalytics } from '@/modules/dashboard/domain/types';
import { href, type Filters, type LinkFilters, type Range } from '@/modules/dashboard/domain/links';
import {
  allSplit,
  isSplitRow,
  assetRows,
  type BarRow,
  customWindow,
  dashboardView,
  entityTypeRows,
  evidenceRows,
  threatLevelRows,
  revisedReports,
  SEVERITY_LABELS,
  severityRows,
  type SplitRow,
  type CountRow,
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
import { levelBand, severityVar } from '@/lib/ui/severity';
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
            <Panel
              className="lg:col-span-3"
              title="Incidents by type"
              total={data ? sumRows(typeRows(data)) : null}
              subtitle="Open a type for its reports"
            >
              {panel(
                (d) => (
                  <SplitBars emptyText={emptyText} hrefFor={(row) => link({ type: row.key })} incidents={d.total} rows={typeRows(d)} />
                ),
                'h-40',
              )}
            </Panel>
            <Panel
              className="lg:col-span-3"
              title="Top assets"
              total={data ? sumRows(assetRows(data)) : null}
              subtitle="Reports per asset (exact name). A rectangle's area is its report count, and a darker grey means more reports. Shows the top 8 assets only."
            >
              {panel(
                (d) => (
                  <AssetTreemap emptyText={emptyText} hrefFor={(row) => link({ asset: row.key })} rows={assetRows(d)} />
                ),
                'h-40',
              )}
            </Panel>
            <Panel
              className="lg:col-span-3"
              title="Instruments by threat level"
              total={data ? sumRows(threatLevelRows(data)) : null}
              subtitle="Instruments in the counted reports, by threat level. Threat level is an instrument's potential to cause harm, from 1 (lowest) to 5 (highest)."
            >
              {panel(
                (d) => (
                  <RiskLadder emptyText={emptyText} rows={threatLevelRows(d)} />
                ),
                'h-40',
              )}
            </Panel>
            <div className="flex min-w-0 flex-col gap-2.5 lg:col-span-3">
              <Panel
                className="flex-1"
                title="Evidence by kind"
                total={data ? sumRows(evidenceRows(data)) : null}
                subtitle="Entities, instruments and assets in the counted reports. The grid is 100 squares, about 1% each."
              >
                {panel(
                  (d) => (
                    <EvidenceWaffle emptyText={emptyText} rows={evidenceRows(d)} />
                  ),
                  'h-20',
                )}
              </Panel>
              <Panel
                className="flex-1"
                title="Entity types"
                total={data ? sumRows(entityTypeRows(data)) : null}
                subtitle="Reports per entity type, human and animal. One icon stands for 5 reports, and a report can have both, so these are not shares."
              >
                {panel(
                  (d) => (
                    <EntityIcons emptyText={emptyText} rows={entityTypeRows(d)} />
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

/** The sum of the rows a card draws, shown beside its title. */
const sumRows = (rows: { total: number }[] | null) => (rows ? rows.reduce((total, row) => total + row.total, 0) : null);

function Panel({
  title,
  subtitle,
  total,
  className,
  children,
}: {
  title: string;
  subtitle: string;
  total?: number | null;
  className?: string;
  children: ReactNode;
}) {
  return (
    <Card className={cn('min-w-0 gap-1.5 rounded-[14px] border-ink/10 bg-white px-3.5 py-2.5 shadow-none', className)}>
      <CardHeader className="flex flex-row items-center gap-1.5 p-0">
        <CardTitle className="text-[13px] font-bold text-ink">{title}</CardTitle>
        <InfoTip label={`About ${title}`} text={subtitle} />
        {total != null && <span className="ml-auto text-xs font-medium tabular-nums text-ink-caption">Total: {total}</span>}
      </CardHeader>
      <CardContent className="flex min-h-0 min-w-0 flex-1 flex-col p-0">{children}</CardContent>
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
    <div className="flex flex-1 flex-col justify-between gap-2">
      <div className="flex flex-wrap items-center gap-3">
        <Link className="text-4xl leading-none font-semibold text-ink hover:underline" href={link()}>
          {total}
        </Link>
        <IncidentsChip count={data.total} versions={total} />
      </div>
      {versions && (
        <>
          <div aria-hidden="true" className="flex h-4 gap-0.5 overflow-hidden rounded-full bg-ink/8">
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
        Every AI and human version of a report counts.
        {revised !== null &&
          ` ${revised} of the ${data.total} ${data.total === 1 ? 'incident has' : 'incidents have'} more than one version.`}
      </p>
    </div>
  );
}

/** Neutral chip beside the total: how many incidents (one per video) those report versions belong to. */
function IncidentsChip({ count, versions }: { count: number; versions: number }) {
  const explanation = `${versions} report ${versions === 1 ? 'version' : 'versions'} across ${count} ${count === 1 ? 'incident' : 'incidents'} (one incident per video)`;
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            aria-label={explanation}
            className="inline-flex items-center rounded-full border border-ink/10 bg-ink/5 px-2.5 py-1 text-xs font-semibold text-ink tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ink/40"
            type="button"
          >
            {count} {count === 1 ? 'incident' : 'incidents'}
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

/** A threat level takes the colour of its severity band (`levelBand`), the same mapping severity uses. */
const threatLevelColor = (level: number): string => {
  const band = levelBand(level);
  return band ? severityVar[band] : 'var(--ink)';
};

/** Row labels lean back by this many degrees, so they take less width and the bars get more of the card. */
const TICK_TILT = -30;

/** A label of several words breaks into two lines at the space nearest its middle. */
function tickLines(label: string): string[] {
  const shown = label.length > MAX_TICK_LENGTH ? `${label.slice(0, MAX_TICK_LENGTH - 1)}…` : label;
  const middle = shown.length / 2;
  const spaces = [...shown.matchAll(/ /g)].map((m) => m.index ?? 0);
  if (!spaces.length) return [shown];
  const at = spaces.reduce((best, i) => (Math.abs(i - middle) < Math.abs(best - middle) ? i : best));
  return [shown.slice(0, at), shown.slice(at + 1)];
}

function RowTick({ x = 0, y = 0, row, href: url }: { x?: number; y?: number; row: BarRow; href?: string }) {
  const lines = tickLines(row.label);
  const label = (
    <text className="fill-ink text-xs capitalize" textAnchor="end" transform={`rotate(${TICK_TILT} ${x} ${y})`} x={x} y={y}>
      <title>{row.label}</title>
      {lines.map((line, i) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length list that never reorders
        <tspan dy={i === 0 ? (lines.length > 1 ? -2 : 4) : 12} key={i} x={x}>
          {line}
        </tspan>
      ))}
    </text>
  );
  if (!url) return label;
  return (
    <Link aria-label={`${row.label}: ${row.total} reports`} className="hover:underline" href={url}>
      {label}
    </Link>
  );
}

const ROW_HEIGHT = 36;
const LABEL_ANCHOR = 1e-6;

/** Top assets as a treemap: a rectangle's area follows its report count. The RPC returns the top eight only. */
function AssetTreemap({ rows, emptyText, hrefFor }: { rows: BarRow[]; emptyText: string; hrefFor: (row: BarRow) => string }) {
  const router = useRouter();
  const [hover, setHover] = useState<number | null>(null);
  if (!rows.length) return <NoData text={emptyText} />;
  const max = Math.max(...rows.map((row) => row.total));
  const data = rows.map((row) => ({ name: row.label, size: row.total, key: row.key }));
  return (
    <ChartContainer config={totalConfig} className="aspect-auto w-full flex-1" style={{ minHeight: 8 * ROW_HEIGHT }}>
      <Treemap
        content={
          <AssetCell hover={hover} max={max} onHover={setHover} onOpen={(index) => rows[index] && router.push(hrefFor(rows[index]))} />
        }
        data={data}
        dataKey="size"
        isAnimationActive={false}
      />
    </ChartContainer>
  );
}

/** A small hover tip for a type: its share of all incidents and how many of them are official. */
function ShareTip({ active, payload, incidents }: { active?: boolean; payload?: Array<{ payload?: BarRow }>; incidents: number }) {
  const row = payload?.[0]?.payload;
  if (!active || !row) return null;
  const official = isSplitRow(row) ? row.official : null;
  return (
    <div className="rounded-md border border-ink/10 bg-white px-2 py-1 text-xs whitespace-nowrap text-ink shadow-sm">
      <span className="font-semibold">{Math.round((row.total / incidents) * 100)}%</span> of incidents
      {official !== null && <span className="text-ink-caption"> · {official} official</span>}
    </div>
  );
}

/** The asset size token (slate) mixed with white by `SLATE_MIN` to 100 percent: the share follows the tile's count over the largest count. */
const SLATE = 'var(--color-asset-size)';
const SLATE_MIN = 25;

/** One treemap rectangle: one slate colour, deeper for a bigger count; outlined on hover while the others step back. */
function AssetCell(props: {
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  index?: number;
  name?: string;
  size?: number;
  depth?: number;
  hover?: number | null;
  max?: number;
  onHover?: (index: number | null) => void;
  onOpen?: (index: number) => void;
}) {
  const { x = 0, y = 0, width = 0, height = 0, index = 0, name = '', size = 0, depth = 0, hover = null, max = 1, onHover, onOpen } = props;
  if (depth < 1) return <g />;
  const depthPct = SLATE_MIN + ((100 - SLATE_MIN) * size) / Math.max(1, max);
  const base = `color-mix(in srgb, ${SLATE} ${depthPct.toFixed(1)}%, white)`;
  const active = hover === index;
  const textColor = depthPct >= 85 ? '#fff' : 'var(--ink)';
  const roomy = width > 36 && height > 34;
  return (
    // biome-ignore lint/a11y/useSemanticElements: an SVG group cannot be an anchor; the treemap tile is also a keyboard-reachable Library link via its list
    <g
      aria-label={`${name}: ${size} reports`}
      className="cursor-pointer"
      onClick={() => onOpen?.(index)}
      onMouseEnter={() => onHover?.(index)}
      onMouseLeave={() => onHover?.(null)}
      opacity={hover !== null && !active ? 0.55 : 1}
      role="link"
    >
      <title>{`${name}: ${size} reports`}</title>
      <rect
        fill={base}
        height={height}
        rx={6}
        stroke={active ? 'var(--ink)' : 'var(--card)'}
        strokeWidth={active ? 3 : 2}
        width={width}
        x={x}
        y={y}
      />
      {roomy &&
        (height < 56 ? (
          <text className="text-xs font-medium capitalize" fill={textColor} stroke="none" x={x + 8} y={y + height / 2 + 4}>
            {name.length > Math.floor((width - 8) / 7) - 3 ? `${name.slice(0, Math.max(2, Math.floor((width - 8) / 7) - 4))}…` : name}
            <tspan className="text-sm font-bold" dx={5}>
              {size}
            </tspan>
          </text>
        ) : (
          <>
            <text className="text-xs font-medium capitalize" fill={textColor} stroke="none" x={x + 8} y={y + 18}>
              {name.length > Math.floor((width - 8) / 7) ? `${name.slice(0, Math.max(2, Math.floor((width - 8) / 7) - 1))}…` : name}
            </text>
            <text className="text-sm font-bold" fill={textColor} stroke="none" x={x + 8} y={y + height - 10}>
              {size}
            </text>
          </>
        ))}
    </g>
  );
}

const EVIDENCE_COLORS = ['var(--chart-1)', 'var(--chart-3)', 'var(--chart-5)'];

/** Evidence by kind as a 10 by 10 waffle, about 1% a square, with each kind's count and share beside it. */
function EvidenceWaffle({ rows, emptyText }: { rows: SplitRow[] | null; emptyText: string }) {
  const [hover, setHover] = useState<string | null>(null);
  if (!rows) return <NoData text="Evidence counts are not available yet." />;
  const sum = rows.reduce((total, row) => total + row.total, 0);
  if (!sum) return <NoData text={emptyText} />;
  const squares = waffleSquares(rows);
  const cells = rows.flatMap((row, index) =>
    Array.from({ length: squares[index] }, () => ({
      key: row.key,
      label: row.label,
      color: EVIDENCE_COLORS[index % EVIDENCE_COLORS.length],
    })),
  );
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: mouse-leave only clears the hover dim; the waffle squares are decoration for the keyboard-reachable list beside them
    <div className="flex min-h-0 flex-1 items-center justify-center gap-5" onMouseLeave={() => setHover(null)}>
      <div
        aria-label={`Evidence items: ${rows.map((row) => `${row.label} ${row.total}`).join(', ')}`}
        className="grid size-28 shrink-0 grid-cols-10 gap-0.5"
        role="img"
      >
        {cells.map((cell, i) => (
          // biome-ignore lint/a11y/noStaticElementInteractions: hover dims the other kinds; the same figures are in the list beside the waffle
          <span
            className="rounded-[2px] transition-[opacity,transform] hover:scale-110"
            // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length waffle that never reorders
            key={i}
            onMouseEnter={() => setHover(cell.key)}
            style={{ background: cell.color, opacity: hover && hover !== cell.key ? 0.3 : 1 }}
            title={`${cell.label}: ${rows.find((row) => row.key === cell.key)?.total ?? 0}`}
          />
        ))}
      </div>
      <ul className="flex min-w-0 flex-col gap-1">
        {rows.map((row, index) => (
          <li
            className="flex items-center gap-2 rounded-lg px-2 py-1 hover:bg-ink/5"
            key={row.key}
            onMouseEnter={() => setHover(row.key)}
            title={`${row.label}: ${row.total} (${row.official} official, ${row.notOfficial} not yet official)`}
          >
            <span
              aria-hidden="true"
              className="size-2.5 shrink-0 rounded-xs"
              style={{ background: EVIDENCE_COLORS[index % EVIDENCE_COLORS.length] }}
            />
            <span className="text-xs font-medium text-ink">{row.label}</span>
            <span className="ml-auto w-9 pl-2 text-right text-xs text-ink-caption tabular-nums">
              {Math.round((row.total / sum) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** One icon stands for this many reports, so the busiest card (69 human reports) fits on one row. */
const REPORTS_PER_ICON = 5;

/** Entity types as an icon array, one icon per REPORTS_PER_ICON reports. Human and animal only; a report can have both, so these are not shares. */
function EntityIcons({ rows, emptyText }: { rows: BarRow[]; emptyText: string }) {
  const shown = rows.filter((row) => row.key === 'human' || row.key === 'animal');
  if (!shown.length) return <NoData text={emptyText} />;
  return (
    <div className="flex min-h-0 flex-1 flex-col justify-center gap-3">
      {shown.map((row) => {
        const Icon = row.key === 'animal' ? PawPrintIcon : UserRoundIcon;
        const color = row.key === 'animal' ? 'var(--chart-3)' : 'var(--chart-1)';
        const count = row.total > 0 ? Math.max(1, Math.round(row.total / REPORTS_PER_ICON)) : 0;
        return (
          <div
            className="flex items-center gap-4"
            key={row.key}
            title={`${row.label}: ${row.total} reports (1 icon = ${REPORTS_PER_ICON} reports; a report can have both)`}
          >
            <div className="flex w-16 shrink-0 flex-col">
              <span className="flex items-center gap-1 text-xs font-medium capitalize" style={{ color }}>
                <Icon aria-hidden="true" className="size-4" fill={color} stroke={color} strokeWidth={1.5} />
                {row.label}
              </span>
              <span className="text-base font-semibold tabular-nums text-ink">{row.total}</span>
            </div>
            <div aria-hidden="true" className="flex min-w-0 flex-1 flex-wrap gap-0.5">
              {Array.from({ length: count }, (_, i) => (
                // biome-ignore lint/suspicious/noArrayIndexKey: fixed-length list that never reorders
                <Icon className="size-6 transition-transform hover:scale-110" fill={color} key={i} stroke={color} strokeWidth={1.5} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

const THREAT_LEVELS = [5, 4, 3, 2, 1] as const;

/**
 * Instruments by threat level as a risk ladder: five steps, level 5 at the top, always shown, even at 0. Every step is the same width;
 * the fill inside it is the count over the largest count, so nothing else encodes size.
 */
function RiskLadder({ rows, emptyText }: { rows: CountRow[]; emptyText: string }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!rows.length) return <NoData text={emptyText} />;
  const counts = new Map(rows.map((row) => [Number(row.key), row.total]));
  const max = Math.max(1, ...counts.values());
  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: mouse-leave only clears the hover dim
    <div className="flex min-h-0 flex-1 flex-col gap-1.5" onMouseLeave={() => setHover(null)} style={{ minHeight: 8 * ROW_HEIGHT }}>
      {THREAT_LEVELS.map((level) => {
        const count = counts.get(level) ?? 0;
        const color = threatLevelColor(level);
        const active = hover === level;
        return (
          <Tooltip key={level}>
            <TooltipTrigger asChild>
              {/* biome-ignore lint/a11y/noStaticElementInteractions: hover dims the other rows; the figures are in the row text */}
              <div
                className="flex min-h-0 flex-1 items-center gap-3 transition-opacity duration-150"
                onMouseEnter={() => setHover(level)}
                style={{ opacity: hover !== null && !active ? 0.55 : 1 }}
              >
                <span className="w-14 shrink-0 text-xs font-medium text-ink">Level {level}</span>
                <div
                  className="relative h-full min-w-0 flex-1 overflow-hidden rounded-lg transition-[outline] duration-150"
                  style={{ background: `color-mix(in srgb, ${color} 18%, white)`, outline: active ? '2px solid var(--ink)' : undefined }}
                >
                  <div
                    className="absolute inset-y-0 left-0 transition-[filter] duration-150"
                    style={{ width: `${(count / max) * 100}%`, background: color, filter: active ? 'brightness(0.85)' : undefined }}
                  />
                  <span
                    className="absolute inset-y-0 flex items-center text-lg font-semibold tabular-nums"
                    style={
                      count / max >= 0.2
                        ? { right: `calc(${(1 - count / max) * 100}% + 12px)`, color: '#fff' }
                        : { left: `calc(${(count / max) * 100}% + 10px)`, color: 'var(--ink)' }
                    }
                  >
                    {count}
                  </span>
                </div>
              </div>
            </TooltipTrigger>
            <TooltipContent side="right">
              {count} {count === 1 ? 'instrument' : 'instruments'} at threat level {level}
            </TooltipContent>
          </Tooltip>
        );
      })}
    </div>
  );
}

/**
 * Rows of official and not-yet-official bars, or of totals alone when a row has no split. With hrefFor, each row opens its
 * reports; without it, the rows are read only.
 */
function SplitBars({
  rows,
  emptyText,
  hrefFor,
  colorFor,
  incidents,
}: {
  rows: BarRow[];
  emptyText: string;
  hrefFor?: (row: BarRow) => string;
  colorFor?: (row: BarRow) => string;
  incidents?: number;
}) {
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
    <ChartContainer
      config={split ? splitConfig : totalConfig}
      className="aspect-auto w-full flex-1"
      style={{ minHeight: rows.length * ROW_HEIGHT }}
    >
      <BarChart accessibilityLayer barCategoryGap="4%" data={rows} layout="vertical" margin={{ top: 0, right: 36, left: 0, bottom: 0 }}>
        {/* Headroom past the longest bar, so its total label is not clipped at the chart's edge. */}
        <XAxis allowDecimals={false} domain={[0, (dataMax: number) => dataMax]} hide type="number" />
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
          width={Math.min(
            112,
            Math.max(...rows.flatMap((row) => tickLines(row.label).map((line) => line.length))) *
              6 *
              Math.cos((TICK_TILT * Math.PI) / 180) +
              14,
          )}
        />
        {incidents ? (
          <ChartTooltip content={<ShareTip incidents={incidents} />} cursor={false} />
        ) : (
          <ChartTooltip content={<ChartTooltipContent />} cursor={false} />
        )}
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
          >
            {colorFor && rows.map((row) => <Cell fill={colorFor(row)} key={row.key} />)}
          </Bar>
        )}
        {/* Recharts drops a label on a zero-width bar, so the total hangs off a sliver at the end of the stack. */}
        <Bar dataKey={() => LABEL_ANCHOR} fill="transparent" isAnimationActive={false} legendType="none" stackId="split" tooltipType="none">
          <LabelList className="fill-ink font-semibold" dataKey="total" fontSize={12} offset={8} position="right" />
        </Bar>
      </BarChart>
    </ChartContainer>
  );
}

/** Squares per band out of 100, by largest remainder, so the grid always adds up to exactly 100. */
function waffleSquares(rows: SplitRow[]): number[] {
  const total = rows.reduce((sum, row) => sum + row.total, 0);
  if (!total) return rows.map(() => 0);
  const exact = rows.map((row) => (row.total / total) * 100);
  const squares = exact.map(Math.floor);
  let left = 100 - squares.reduce((sum, n) => sum + n, 0);
  exact
    .map((value, index) => ({ index, rest: value - Math.floor(value) }))
    .sort((a, b) => b.rest - a.rest)
    .forEach(({ index }) => {
      if (left > 0 && rows[index].total > 0) {
        squares[index] += 1;
        left -= 1;
      }
    });
  return squares;
}

/**
 * Severity bands as a donut. The list is the accessible control: each band is a button that filters the page, so no
 * slice has to be hit by a pointer.
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
    <div className="flex flex-col items-center justify-center gap-2">
      <div aria-label={`Severity of ${rated} rated reports: ${summary}`} className="relative size-36 shrink-0" role="img">
        <ChartContainer config={severityConfig} className="aspect-square size-full">
          <PieChart>
            <ChartTooltip content={<ChartTooltipContent hideLabel />} />
            <Pie
              activeShape={PopSector}
              cursor="default"
              data={rows}
              dataKey="total"
              inactiveShape={DimSector}
              innerRadius="50%"
              {...motion}
              nameKey="key"
              outerRadius="88%"
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
          <span className="text-2xl leading-none font-semibold text-ink">{rated}</span>
          <span className="text-xs text-ink-caption">{unrated ? 'rated' : 'reports'}</span>
        </div>
      </div>
      <ul className="grid w-full min-w-0 grid-cols-3 gap-1">
        {rows.map((row) => {
          const pressed = selected === row.key;
          return (
            <li key={row.key}>
              <button
                aria-pressed={pressed}
                className={cn(
                  'flex w-full flex-col items-center gap-0.5 rounded-lg px-1.5 py-1 text-center transition-colors hover:bg-ink/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  pressed && 'bg-ink/5 ring-1 ring-ink/20',
                )}
                onClick={() => onSelect(row)}
                title={`${row.official} official, ${row.notOfficial} not yet official`}
                type="button"
              >
                <span className="flex items-center gap-1.5">
                  <span
                    aria-hidden="true"
                    className="size-2.5 shrink-0 rounded-xs"
                    style={{ background: severityVar[row.key as keyof typeof severityVar] }}
                  />
                  <span className="text-xs font-medium text-ink">{row.label}</span>
                </span>
              </button>
            </li>
          );
        })}
        {unrated > 0 && <li className="col-span-3 px-2 pt-1 text-center text-xs text-ink-caption">No severity: {unrated}</li>}
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
      <div className="flex flex-1 flex-col overflow-x-auto p-2">
        <div className="flex min-w-[440px] flex-1 flex-col">
          <div className="grid grid-cols-[32px_repeat(24,1fr)] gap-0.5 text-[10px] text-ink-caption">
            <span />
            {HOURS_OF_DAY.map((h) => (
              <span key={`label-${h}`}>{h % 6 === 0 ? `${h}:00` : ''}</span>
            ))}
          </div>
          {DAY_NAMES.map((name, d) => (
            <div className="mt-0.5 grid flex-1 grid-cols-[32px_repeat(24,1fr)] gap-0.5" key={name}>
              <span className="text-[10px] text-ink-caption">{name}</span>
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
                          'relative h-full min-h-4 rounded-xs bg-(--cell) transition duration-150 hover:z-10 hover:bg-(--cell-hover) hover:ring-2 hover:ring-ink motion-safe:hover:scale-150 focus-visible:z-10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
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
