// SPDX-License-Identifier: Apache-2.0
'use client';
import Link from 'next/link';
import { useEffect, useMemo, useState, type ReactNode } from 'react';
import type { DashboardAnalytics, ModelCoverage, RankedValue, SeverityCounts, TypeDetail } from '@/modules/dashboard/domain/types';
import { href, type Filters, type LinkFilters, type Range } from '@/modules/dashboard/domain/links';
import { getViewerTimeZone } from '@/lib/time';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { Progress } from '@/components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from '@/components/ui/chart';
import { Area, AreaChart, Bar, BarChart, CartesianGrid, XAxis } from 'recharts';
import { cn } from 'cn';

const NONE: Filters = { type: '', severity: '', day: '', hour: '' };
const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const EMPTY: DashboardAnalytics = {
  total: 0,
  videos: { uploaded: 0, withOfficial: 0, awaitingSelection: 0, withoutReport: 0 },
  previous: null,
  averageConfidence: null,
  confidenceNotProvided: 0,
  severity: { low: 0, medium: 0, high: 0 },
  revisions: { ai: 0, human: 0 },
  types: [],
  trend: [],
  heatmap: [],
  confidence: [],
  entityTypes: [],
  topInstruments: [],
  topAssets: [],
  threatLevels: [],
  modelCoverage: [],
};

export function Dashboard() {
  const [data, setData] = useState(EMPTY);
  const [days, setDays] = useState('30');
  const [compare, setCompare] = useState(true);
  const [filters, setFilters] = useState<Filters>(NONE);
  const [expanded, setExpanded] = useState('');
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
    fetch(`/api/dashboard?${params}`, { cache: 'no-store', signal: controller.signal })
      .then(async (r) => {
        const p = (await r.json()) as { analytics?: DashboardAnalytics; error?: string };
        if (!r.ok || !p.analytics) throw new Error(p.error || 'Could not load dashboard');
        setData({ ...EMPTY, ...p.analytics });
      })
      .catch((e: Error) => {
        if (e.name !== 'AbortError') setError(e.message);
      });
    return () => controller.abort();
  }, [days, filters, range, timeZone]);
  const previous = compare ? data.previous : null;
  const active = Object.values(filters).some(Boolean);
  const maxType = Math.max(1, ...data.types.map((x) => x.count));
  const toggle = (key: keyof Filters, value: string) => setFilters((f) => ({ ...f, [key]: f[key] === value ? '' : value }));
  const link = (extra: LinkFilters = {}) => href({ ...filters, ...extra }, range ?? null);
  return (
    <div className="mx-auto max-w-[1500px] px-6 pb-20 pt-8 lg:px-12">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-mono text-xs uppercase tracking-[.2em] text-moss">Official incidents</p>
          <h1 className="mt-2 text-4xl font-semibold sm:text-5xl">Operations dashboard</h1>
          <p className="mt-3 max-w-3xl text-sm text-ink/50">
            Incident statistics count each video once, through its explicitly selected official report. Videos without an official report
            are counted separately and never assigned to a category. Every number opens the matching reports.
          </p>
        </div>
        <div className="flex items-center gap-4">
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
          <AlertTitle>Error loading dashboard</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <section className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4" data-testid="video-metrics">
        <Metric href="/videos" label="Uploaded videos" note="all time" value={data.videos.uploaded} />
        <Metric
          change={delta(data.total, previous?.total)}
          href={link()}
          label="Official incidents"
          note="in the selected period"
          value={data.total}
        />
        <Metric
          href="/videos?filter=awaiting-selection"
          label="Awaiting official report"
          note="have reports, none selected"
          value={data.videos.awaitingSelection}
        />
        <Metric
          href="/videos?filter=without-report"
          label="Without a report"
          note="no successful analysis yet"
          value={data.videos.withoutReport}
        />
      </section>
      <section className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Metric
          change={delta(data.revisions.human, previous?.human)}
          href={link({ kind: 'human' })}
          label="Human-edited"
          value={data.revisions.human}
        />
        <Metric
          change={delta(data.revisions.ai, previous?.ai)}
          href={link({ kind: 'ai' })}
          label="AI as generated"
          value={data.revisions.ai}
        />
        <Metric
          change={delta(data.severity.high, previous?.high)}
          href={link({ severity: 'high' })}
          label="High severity"
          value={data.severity.high}
        />
        <Metric
          href={link()}
          label="Model confidence"
          note={
            data.averageConfidence === null
              ? `not provided by the models (${data.confidenceNotProvided})`
              : `${data.confidenceNotProvided} not provided`
          }
          value={data.averageConfidence === null ? '—' : `${Math.round(data.averageConfidence * 100)}%`}
        />
      </section>
      <div className="mt-6 grid gap-6 xl:grid-cols-[1.4fr_.8fr]">
        <Panel title="Official incidents over time" subtitle="By official report date (UTC days)">
          <Trend points={data.trend} />
        </Panel>
        <Panel title="Severity breakdown" subtitle="Click a segment to cross-filter">
          <Severity counts={data.severity} selected={filters.severity} onSelect={(v) => toggle('severity', v)} />
        </Panel>
      </div>
      <div className="mt-6 grid gap-6 xl:grid-cols-[1.2fr_.8fr]">
        <Panel title="Incidents by type" subtitle="Expand a row for evidence and severity">
          <div className="space-y-2">
            <Accordion type="single" collapsible value={expanded} onValueChange={setExpanded} className="space-y-2">
              {data.types.map((item) => (
                <TypeRow filters={filters} item={item} key={item.type} max={maxType} range={range ?? null} />
              ))}
            </Accordion>
            {!data.types.length && <Empty />}
          </div>
        </Panel>
        <Panel title="Official reports by version" subtitle="As the model generated them, or saved by a reviewer">
          <Funnel data={data} />
        </Panel>
      </div>
      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Panel title="Entities by type" subtitle="Incidents involving each entity type">
          <Leaders items={data.entityTypes} linkFor={(x) => link({ entityType: x.label })} />
        </Panel>
        <Panel title="Top instruments" subtitle="Incidents per instrument (exact name)">
          <Leaders items={data.topInstruments} linkFor={(x) => link({ instrument: x.label })} />
        </Panel>
        <Panel title="Top assets" subtitle="Incidents per asset (exact name)">
          <Leaders items={data.topAssets} linkFor={(x) => link({ asset: x.label })} />
        </Panel>
      </div>
      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Panel
          title="Report activity by day and time"
          subtitle={`Official report generation time (${timeZone}); click a cell to cross-filter`}
        >
          <Heatmap
            data={data.heatmap}
            selected={`${filters.day}-${filters.hour}`}
            onSelect={(d, h) =>
              setFilters((f) =>
                f.day === String(d) && f.hour === String(h) ? { ...f, day: '', hour: '' } : { ...f, day: String(d), hour: String(h) },
              )
            }
            timeZone={timeZone}
          />
        </Panel>
        <Panel title="Instrument threat levels" subtitle="Instruments in official incidents, by rated threat">
          <ThreatLevels data={data.threatLevels} />
        </Panel>
      </div>
      <div className="mt-6 grid gap-6 xl:grid-cols-2">
        <Panel
          title="Confidence distribution"
          subtitle={
            data.averageConfidence === null
              ? 'No model provided a confidence value'
              : `Average ${Math.round(data.averageConfidence * 100)}% · ${data.confidenceNotProvided} not provided`
          }
        >
          <Histogram data={data.confidence} />
        </Panel>
        <Panel title="Analyses by model" subtitle="Every analysis attempt in the period, by outcome (all runs, not only official reports)">
          <Coverage rows={data.modelCoverage} />
        </Panel>
      </div>
    </div>
  );
}

function delta(now: number, before?: number) {
  if (before === undefined) return null;
  return before ? Math.round(((now - before) / before) * 100) : now ? 100 : 0;
}

function Metric({
  label,
  value,
  href: url,
  change = null,
  note,
}: {
  label: string;
  value: number | string;
  href: string;
  change?: number | null;
  note?: string;
}) {
  return (
    <Card className="rounded-2xl border-ink/10 bg-white p-0 shadow-none transition-shadow hover:shadow-panel focus-within:ring-2 focus-within:ring-ring">
      <Link className="block rounded-2xl p-5 focus:outline-none" href={url}>
        <p className="text-sm text-ink/50">{label}</p>
        <p className="mt-2 text-4xl font-semibold text-ink">{value}</p>
        {note && <p className="mt-1 text-[11px] text-ink-caption">{note}</p>}
        {change !== null && (
          <p className="mt-2 text-xs text-ink-caption">
            {change > 0 ? '+' : ''}
            {change}% vs. previous
          </p>
        )}
      </Link>
    </Card>
  );
}

function Panel({ title, subtitle, children }: { title: string; subtitle: string; children: ReactNode }) {
  return (
    <Card className="rounded-3xl border-ink/10 bg-white p-6 shadow-none">
      <CardHeader className="gap-1 p-0">
        <CardTitle className="text-lg font-semibold text-ink">{title}</CardTitle>
        <CardDescription className="text-xs text-ink-caption">{subtitle}</CardDescription>
      </CardHeader>
      <CardContent className="mt-5 p-0">{children}</CardContent>
    </Card>
  );
}

function TypeRow({ item, max, filters, range }: { item: TypeDetail; max: number; filters: Filters; range: Range }) {
  const typeFilters = { ...filters, type: item.type };
  return (
    <AccordionItem value={item.type} className="rounded-2xl border border-ink/8 px-4 not-last:border-b-ink/8">
      <div className="flex items-center gap-3 py-2">
        <Link className="min-w-0 flex-1 hover:opacity-80" href={href(typeFilters, range)}>
          <div className="flex justify-between text-sm">
            <strong className="capitalize text-ink">{item.type}</strong>
            <span className="text-ink">{item.count}</span>
          </div>
          <div className="mt-2">
            <Progress value={(item.count / max) * 100} className="h-2 bg-ink/8 [&>[data-slot=progress-indicator]]:bg-signal" />
          </div>
        </Link>
        <AccordionTrigger
          className="flex-none py-2 text-ink/50 hover:no-underline hover:text-ink"
          aria-label={`Toggle ${item.type} details`}
        />
      </div>
      <AccordionContent className="border-t border-ink/8 pt-4 pb-2">
        <div className="grid gap-4 md:grid-cols-3">
          <Evidence title="Entity types" items={item.entities} linkFor={(x) => href({ ...typeFilters, entityType: x.label }, range)} />
          <Evidence title="Instruments" items={item.instruments} linkFor={(x) => href({ ...typeFilters, instrument: x.label }, range)} />
          <Evidence title="Assets affected" items={item.assets} linkFor={(x) => href({ ...typeFilters, asset: x.label }, range)} />
        </div>
        <div className="mt-5">
          <p className="text-[10px] font-bold uppercase text-ink-caption">Severity split</p>
          <Severity compact counts={item.severity} selected="" onSelect={() => undefined} />
        </div>
        <Link className="mt-5 inline-block text-sm font-semibold text-moss" href={href(typeFilters, range)}>
          View all {item.type} reports →
        </Link>
      </AccordionContent>
    </AccordionItem>
  );
}

function Evidence({ title, items, linkFor }: { title: string; items: RankedValue[]; linkFor: (x: RankedValue) => string }) {
  return (
    <div>
      <p className="text-[10px] font-bold uppercase text-ink-caption">{title}</p>
      <div className="mt-2 space-y-1">
        {items.map((x) => (
          <Link className="flex gap-2 text-sm text-moss hover:underline" href={linkFor(x)} key={x.label}>
            <span className="min-w-0 flex-1 truncate">{x.label}</span>
            <span>{x.count}</span>
          </Link>
        ))}
        {!items.length && <span className="text-xs text-ink/35">None identified</span>}
      </div>
    </div>
  );
}

function Severity({
  counts,
  selected,
  onSelect,
  compact = false,
}: {
  counts: SeverityCounts;
  selected: string;
  onSelect: (v: string) => void;
  compact?: boolean;
}) {
  const total = counts.low + counts.medium + counts.high;
  const rows = [
    ['low', 'Low', 'bg-signal'],
    ['medium', 'Medium', 'bg-amber-400'],
    ['high', 'High', 'bg-clay'],
  ] as const;
  return (
    <div>
      <div className={`flex overflow-hidden rounded-full bg-ink/8 ${compact ? 'mt-2 h-2' : 'h-5'}`}>
        {rows.map(([k, label, color]) => (
          <button
            aria-label={`${label} severity`}
            className={`${color} ${selected && selected !== k ? 'opacity-25' : ''} transition-opacity focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring`}
            disabled={compact}
            key={k}
            onClick={() => onSelect(k)}
            style={{ width: `${total ? (counts[k] / total) * 100 : 0}%` }}
            type="button"
          />
        ))}
      </div>
      <div className="mt-3 grid grid-cols-3 text-xs">
        {rows.map(([k, label]) => (
          <button
            disabled={compact}
            key={k}
            onClick={() => onSelect(k)}
            type="button"
            className="rounded p-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <strong className="block text-base text-ink">{counts[k]}</strong>
            <span className="text-ink/60">{label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

const trendChartConfig = {
  count: {
    label: 'Incidents',
    color: '#174f3b',
  },
} satisfies ChartConfig;

function Trend({ points }: { points: DashboardAnalytics['trend'] }) {
  if (!points.length || !points.some((x) => x.count)) {
    return <Empty />;
  }

  return (
    <div className="w-full">
      <ChartContainer config={trendChartConfig} className="h-48 w-full aspect-auto">
        <AreaChart data={points} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
          <defs>
            <linearGradient id="fillTrend" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#174f3b" stopOpacity={0.35} />
              <stop offset="95%" stopColor="#174f3b" stopOpacity={0.0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} strokeDasharray="3 3" className="stroke-ink/10" />
          <XAxis dataKey="date" tickLine={false} axisLine={false} tickMargin={8} className="text-[10px] text-ink-caption" />
          <ChartTooltip content={<ChartTooltipContent indicator="line" />} />
          <Area dataKey="count" type="monotone" fill="url(#fillTrend)" fillOpacity={0.4} stroke="#174f3b" strokeWidth={2} />
        </AreaChart>
      </ChartContainer>
      <div className="mt-2 flex justify-between text-[10px] text-ink-caption">
        <span>{points[0]?.date}</span>
        <span>{points.at(-1)?.date}</span>
      </div>
    </div>
  );
}

const HOURS_OF_DAY = Array.from({ length: 24 }, (_, h) => h);
const CONFIDENCE_BUCKETS = Array.from({ length: 10 }, (_, b) => b);

function Heatmap({
  data,
  selected,
  onSelect,
  timeZone,
}: {
  data: DashboardAnalytics['heatmap'];
  selected: string;
  onSelect: (d: number, h: number) => void;
  timeZone: string;
}) {
  const map = useMemo(() => new Map(data.map((x) => [`${x.day}-${x.hour}`, x.count])), [data]);
  const max = Math.max(1, ...data.map((x) => x.count));
  return (
    <TooltipProvider delayDuration={100}>
      <div className="overflow-x-auto">
        <div className="min-w-[520px]">
          {DAYS.map((name, d) => (
            <div className="mt-1 grid grid-cols-[32px_repeat(24,1fr)] gap-1" key={name}>
              <span className="text-[10px]">{name}</span>
              {HOURS_OF_DAY.map((h) => {
                const count = map.get(`${d}-${h}`) || 0;
                return (
                  <Tooltip key={`hour-${h}`}>
                    <TooltipTrigger asChild>
                      <button
                        aria-label={`${name} ${h}:00 ${timeZone}: ${count}`}
                        className={cn(
                          'aspect-square rounded-xs transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                          selected === `${d}-${h}` ? 'ring-2 ring-ink' : '',
                        )}
                        onClick={() => onSelect(d, h)}
                        style={{ background: `rgba(49,91,58,${count ? 0.15 + (count / max) * 0.85 : 0.04})` }}
                        type="button"
                      />
                    </TooltipTrigger>
                    <TooltipContent side="top">
                      <span>{`${name} ${h}:00 ${timeZone} · ${count}`}</span>
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

function Funnel({ data }: { data: DashboardAnalytics }) {
  const rows = [
    ['AI as generated', data.revisions.ai, '[&>[data-slot=progress-indicator]]:bg-clay/50'],
    ['Human-edited', data.revisions.human, '[&>[data-slot=progress-indicator]]:bg-signal'],
  ] as const;
  const max = Math.max(1, ...rows.map((x) => x[1]));
  return (
    <div className="space-y-4">
      {rows.map(([label, count, indicatorColor]) => (
        <div key={label}>
          <div className="flex justify-between text-sm">
            <span>{label}</span>
            <strong>{count}</strong>
          </div>
          <div className="mt-2">
            <Progress value={(count / max) * 100} className={cn('h-7 rounded-sm bg-ink/5', indicatorColor)} />
          </div>
        </div>
      ))}
    </div>
  );
}

const histogramChartConfig = {
  count: {
    label: 'Analyses',
    color: '#174f3b',
  },
} satisfies ChartConfig;

function Histogram({ data }: { data: DashboardAnalytics['confidence'] }) {
  if (!data.length) return <p className="text-sm text-ink-caption">No confidence values were provided.</p>;
  const map = new Map(data.map((x) => [x.bucket, x.count]));
  const chartData = CONFIDENCE_BUCKETS.map((b) => ({
    bucket: `${b * 10}%`,
    count: map.get(b) || 0,
  }));

  return (
    <div className="w-full">
      <ChartContainer config={histogramChartConfig} className="h-48 w-full aspect-auto">
        <BarChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" className="stroke-ink/10" />
          <XAxis dataKey="bucket" tickLine={false} axisLine={false} tickMargin={8} className="text-[10px] text-ink-caption" />
          <ChartTooltip content={<ChartTooltipContent />} />
          <Bar dataKey="count" fill="#174f3b" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ChartContainer>
    </div>
  );
}

function ThreatLevels({ data }: { data: DashboardAnalytics['threatLevels'] }) {
  const map = new Map(data.map((x) => [x.level, x.count]));
  const max = Math.max(1, ...data.map((x) => x.count));
  return data.length ? (
    <div className="space-y-3">
      {[5, 4, 3, 2, 1].map((level) => (
        <div className="flex items-center gap-3 text-sm" key={level}>
          <span className="w-16 text-ink/55">Threat {level}</span>
          <div className="flex-1">
            <Progress
              value={((map.get(level) || 0) / max) * 100}
              className="h-3 rounded-sm bg-ink/5 [&>[data-slot=progress-indicator]]:bg-clay/60"
            />
          </div>
          <strong className="w-8 text-right">{map.get(level) || 0}</strong>
        </div>
      ))}
    </div>
  ) : (
    <Empty />
  );
}

function Leaders({ items, linkFor }: { items: RankedValue[]; linkFor: (x: RankedValue) => string }) {
  const max = Math.max(1, ...items.map((x) => x.count));
  return (
    <div className="space-y-4">
      {items.map((x, i) => (
        <Link
          className="group -m-1 block rounded-lg p-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          href={linkFor(x)}
          key={x.label}
        >
          <div className="flex gap-3 text-sm">
            <span className="text-ink/30">{i + 1}</span>
            <span className="min-w-0 flex-1 truncate capitalize group-hover:underline">{x.label}</span>
            <strong>{x.count}</strong>
          </div>
          <div className="ml-6 mt-2">
            <Progress value={(x.count / max) * 100} className="h-1.5 rounded-none bg-ink/8 [&>[data-slot=progress-indicator]]:bg-signal" />
          </div>
        </Link>
      ))}
      {!items.length && <Empty />}
    </div>
  );
}

function Coverage({ rows }: { rows: ModelCoverage[] }) {
  return rows.length ? (
    <div className="overflow-x-auto">
      <Table className="text-xs">
        <TableHeader>
          <TableRow className="border-b border-ink/8 hover:bg-transparent">
            <TableHead className="h-auto whitespace-normal py-1 pr-2 align-bottom font-semibold text-ink-caption">Model</TableHead>
            <TableHead className="h-auto whitespace-normal px-1.5 align-bottom text-ink-caption">With report</TableHead>
            <TableHead className="h-auto whitespace-normal px-1.5 align-bottom text-ink-caption">Valid</TableHead>
            <TableHead className="h-auto whitespace-normal px-1.5 align-bottom text-ink-caption">IDs repaired</TableHead>
            <TableHead className="h-auto whitespace-normal px-1.5 align-bottom text-ink-caption">Earlier</TableHead>
            <TableHead className="h-auto whitespace-normal px-1.5 align-bottom text-ink-caption">Contract failed</TableHead>
            <TableHead className="h-auto whitespace-normal px-1.5 align-bottom text-ink-caption">Request failed</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow className="border-t border-ink/8 hover:bg-black/5" key={row.model}>
              <TableCell className="max-w-[160px] truncate py-2 pr-2 font-semibold text-ink" title={row.model}>{row.model}</TableCell>
              <TableCell className="px-1.5">{row.withReport}</TableCell>
              <TableCell className="px-1.5">{row.validFirstPass}</TableCell>
              <TableCell className="px-1.5">{row.repaired}</TableCell>
              <TableCell className="px-1.5">{row.legacy}</TableCell>
              <TableCell className="px-1.5">{row.contractFailed}</TableCell>
              <TableCell className="px-1.5">{row.requestFailed}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  ) : (
    <Empty />
  );
}

function Empty() {
  return <p className="text-sm text-ink-caption">No official incidents in this selection.</p>;
}
