// SPDX-License-Identifier: Apache-2.0
'use client';

import { ChartColumnIcon, SearchXIcon } from 'lucide-react';
import { useState, type FormEvent } from 'react';

import { CHART_REQUEST_MAX_LENGTH, type ChartType, type GeneratedChart } from '@/modules/dashboard/domain/generated-chart';
import { useChartRequest } from '@/sections/dashboard/hooks/use-chart-request';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Skeleton } from '@/components/ui/skeleton';
import { Spinner } from '@/components/ui/spinner';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

const EXAMPLES = ['Incident distribution', 'Severity breakdown', 'Trends over time'];

export function ChartRequest() {
  const { state, submit } = useChartRequest();
  const [text, setText] = useState('');
  const [chartType, setChartType] = useState<ChartType>('bar');
  const loading = state.status === 'loading';
  const run = (request: string) => {
    setText(request);
    void submit(request, chartType);
  };
  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    if (text.trim()) void submit(text.trim(), chartType);
  };
  return (
    <Card className="mt-6 rounded-3xl border-ink/10 bg-white p-6 shadow-none" data-testid="chart-request">
      <CardHeader className="gap-1 p-0">
        <CardTitle className="text-lg font-semibold text-ink">Ask for a chart</CardTitle>
        <CardDescription className="text-xs text-ink-caption">
          Pick a chart type and describe one chart. AI only picks what to plot; every figure comes from the incident database. A new request
          replaces the result.
        </CardDescription>
      </CardHeader>
      <CardContent className="mt-5 flex flex-col gap-4 p-0">
        <form className="flex flex-col gap-2 sm:flex-row" onSubmit={onSubmit}>
          <ToggleGroup
            aria-label="Chart type"
            onValueChange={(value) => {
              if (value) setChartType(value as ChartType);
            }}
            type="single"
            value={chartType}
            variant="outline"
          >
            <ToggleGroupItem value="bar">Bar</ToggleGroupItem>
            <ToggleGroupItem value="pie">Pie</ToggleGroupItem>
          </ToggleGroup>
          <Label className="sr-only" htmlFor="chart-request-text">
            Chart request
          </Label>
          <Input
            id="chart-request-text"
            maxLength={CHART_REQUEST_MAX_LENGTH}
            onChange={(event) => setText(event.target.value)}
            placeholder="For example: high severity incidents per month"
            value={text}
          />
          <Button className="shrink-0" disabled={loading || !text.trim()} type="submit">
            {loading ? <Spinner data-icon="inline-start" /> : <ChartColumnIcon data-icon="inline-start" />}
            Create chart
          </Button>
        </form>
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((example) => (
            <Button disabled={loading} key={example} onClick={() => run(example)} size="sm" type="button" variant="outline">
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
                outcome, over the last 7, 30, 90 or 365 days or all time.
              </AlertDescription>
            </Alert>
          )}
          {state.status === 'needs_bar' && (
            <Alert>
              <AlertTitle>That one needs a bar chart</AlertTitle>
              <AlertDescription>
                A pie only works when the parts make one whole. Trends, activity and lists where a report can count twice do not, so pick
                Bar.
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
      {chart.image ? (
        <Tabs defaultValue="chart">
          <TabsList>
            <TabsTrigger value="chart">Chart</TabsTrigger>
            <TabsTrigger value="table">Table</TabsTrigger>
          </TabsList>
          <TabsContent value="chart">
            {/* biome-ignore lint/performance/noImgElement: a data URL our server built, so next/image has nothing to fetch or optimise */}
            <img alt={`${chart.title}, ${chart.scope.join(', ')}`} className="h-auto w-full max-w-xl" src={chart.image} />
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
