// SPDX-License-Identifier: Apache-2.0
'use client';

import dynamic from 'next/dynamic';
import { ChartColumnIcon, SearchXIcon } from 'lucide-react';
import { useState, type FormEvent } from 'react';

import { chartSummary } from '@/modules/dashboard/domain/chart-summary';
import { CHART_REQUEST_MAX_LENGTH, type ChartKind, type GeneratedChart } from '@/modules/dashboard/domain/generated-chart';
import { CHART_REQUEST_ID, CHART_REQUEST_INPUT_ID } from '@/sections/dashboard/chart-request-jump';
import { useChartRequest } from '@/sections/dashboard/hooks/use-chart-request';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { InfoTip } from '@/sections/dashboard/components/FilterBar';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

// Chart.js is loaded only when a chart comes back, so the dashboard page does not carry it.
const ChartJsView = dynamic(() => import('./ChartJsView').then((module) => module.ChartJsView), {
  ssr: false,
  loading: () => <Skeleton className="h-72 w-full rounded-2xl" />,
});

export { CHART_REQUEST_ID, CHART_REQUEST_INPUT_ID };

const EXAMPLES = ['Incident distribution', 'Severity breakdown', 'Trends over time', 'Incident types in October'];
const KIND_LABELS: Record<ChartKind, string> = {
  bar: 'Bar',
  stacked_bar: 'Stacked bar',
  horizontal_bar: 'Horizontal bar',
  donut: 'Donut',
  line: 'Line',
  area: 'Area',
};

export function ChartRequest() {
  const { state, submit } = useChartRequest();
  const [text, setText] = useState('');
  const [chartKind, setChartKind] = useState<ChartKind>('bar');
  const loading = state.status === 'loading';
  const run = (request: string) => {
    setText(request);
    void submit(request, chartKind);
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (text.trim()) void submit(text.trim(), chartKind);
  };
  return (
    <Card
      className="mt-2.5 gap-2 rounded-[14px] border-ink/10 bg-white px-3.5 py-2.5 shadow-none"
      data-testid="chart-request"
      id={CHART_REQUEST_ID}
    >
      <CardContent className="flex flex-col gap-2 p-0">
        <div className="flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-1.5">
            <h2 className="text-[13px] font-bold whitespace-nowrap text-ink">Ask for a chart</h2>
            <InfoTip
              label="About Ask for a chart"
              text="Pick a chart type and describe one chart. AI only picks what to plot; every figure comes from the incident database. A new request replaces the result."
            />
          </div>
          <ToggleGroup
            aria-label="Chart type"
            className="flex-wrap justify-start gap-0.5 rounded-lg bg-secondary p-0.5"
            onValueChange={(value) => {
              if (value) setChartKind(value as ChartKind);
            }}
            spacing={0}
            type="single"
            value={chartKind}
          >
            {(Object.keys(KIND_LABELS) as ChartKind[]).map((kind) => (
              <ToggleGroupItem
                className="h-6 rounded-md px-1.5 text-xs font-normal text-ink-caption data-[state=on]:bg-white data-[state=on]:font-semibold data-[state=on]:text-ink data-[state=on]:shadow-xs"
                key={kind}
                value={kind}
              >
                {KIND_LABELS[kind]}
              </ToggleGroupItem>
            ))}
          </ToggleGroup>
          <form className="flex min-w-[260px] flex-1 gap-2" onSubmit={onSubmit}>
            <Label className="sr-only" htmlFor={CHART_REQUEST_INPUT_ID}>
              Chart request
            </Label>
            <Input
              className="h-7 text-xs"
              id={CHART_REQUEST_INPUT_ID}
              maxLength={CHART_REQUEST_MAX_LENGTH}
              onChange={(event) => setText(event.target.value)}
              placeholder="Describe one chart, for example: incident types in October"
              value={text}
            />
            <Button className="h-7 shrink-0 px-3 text-xs" disabled={loading || !text.trim()} type="submit">
              {loading ? <Spinner data-icon="inline-start" /> : <ChartColumnIcon data-icon="inline-start" />}
              Generate
            </Button>
          </form>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {EXAMPLES.map((example) => (
            <Button
              className="h-6 px-2 text-xs font-normal"
              disabled={loading}
              key={example}
              onClick={() => run(example)}
              size="sm"
              type="button"
              variant="outline"
            >
              {example}
            </Button>
          ))}
        </div>
        <div aria-live="polite">
          {state.status === 'loading' && (
            <div className="flex flex-col gap-3">
              <span className="sr-only">Building the chart</span>
              <Skeleton className="h-5 w-56" />
              <Skeleton className="aspect-[4/3] w-full max-w-xl rounded-2xl" />
            </div>
          )}
          {state.status === 'unsupported' && (
            <Alert>
              <AlertTitle>Can't chart that</AlertTitle>
              <AlertDescription>
                Charts can count reports by incident type, severity, status, version, entity type, instrument, asset or confidence, show
                trends by day, week or month, report activity by weekday or hour, instrument threat levels, and analyses by model or
                outcome. The period can be the last 7, 30, 90 or 365 days, all time, a calendar month, a day, or a range of up to a year
                that starts today or earlier; one that runs past today is charted up to today.
              </AlertDescription>
            </Alert>
          )}
          {state.status === 'needs_bar' && (
            <Alert>
              <AlertTitle>That chart type does not suit this request</AlertTitle>
              <AlertDescription>
                Bar works for every request. A donut needs parts that make one whole, a line or area needs a trend over time, and a stacked
                bar needs reports split by status. Pick another type.
              </AlertDescription>
            </Alert>
          )}
          {state.status === 'error' && (
            <Alert variant="destructive">
              <AlertTitle>Could not create the chart</AlertTitle>
              <AlertDescription>{state.message}</AlertDescription>
            </Alert>
          )}
          {state.status === 'chart' && <Result chart={state.chart} />}
        </div>
      </CardContent>
    </Card>
  );
}

function Result({ chart }: { chart: GeneratedChart }) {
  const drawn = chart.config ?? chart.image;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <h3 className="text-base font-semibold text-ink">{chart.title}</h3>
        <p className="text-xs text-ink-caption">{chart.description}</p>
        <div className="mt-1 flex flex-wrap gap-2">
          {chart.scope.map((item) => (
            <Badge className="font-normal text-ink" key={item} variant="secondary">
              {item}
            </Badge>
          ))}
        </div>
      </div>
      {drawn ? (
        <Tabs defaultValue="chart">
          <TabsList>
            <TabsTrigger value="chart">Chart</TabsTrigger>
            <TabsTrigger value="table">Table</TabsTrigger>
          </TabsList>
          <TabsContent value="chart">
            {chart.config ? (
              <ChartJsView config={chart.config} label={chartSummary(chart)} />
            ) : (
              /* biome-ignore lint/performance/noImgElement: a data URL our server built, so next/image has nothing to fetch or optimise */
              <img alt={chartSummary(chart)} className="h-auto w-full max-w-xl" src={chart.image ?? ''} />
            )}
          </TabsContent>
          <TabsContent value="table">
            <Figures chart={chart} />
          </TabsContent>
        </Tabs>
      ) : (
        <Empty className="border border-ink/10 p-8">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <SearchXIcon />
            </EmptyMedia>
            <EmptyTitle>Nothing to plot</EmptyTitle>
            <EmptyDescription>No records match this chart.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
      {chart.reports && (
        <p className="text-xs text-ink-caption" data-testid="chart-report-totals">
          {chart.reports.total} reports: {chart.reports.official} official, {chart.reports.notOfficial} not official
        </p>
      )}
    </div>
  );
}

function Figures({ chart }: { chart: GeneratedChart }) {
  return (
    <div className="max-h-80 max-w-xl overflow-auto">
      <Table className="text-sm">
        <TableHeader>
          <TableRow>
            <TableHead>{chart.categoryLabel}</TableHead>
            {chart.series.map(({ key, label }) => (
              <TableHead className="text-right" key={key}>
                {label}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {chart.rows.map((row) => (
            <TableRow key={row.category}>
              <TableCell>{row.category}</TableCell>
              {chart.series.map(({ key }) => (
                <TableCell className="text-right" key={key}>
                  {row.values[key] ?? 0}
                </TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
