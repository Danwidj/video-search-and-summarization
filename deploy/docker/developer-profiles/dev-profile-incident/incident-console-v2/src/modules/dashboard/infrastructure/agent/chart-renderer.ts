// SPDX-License-Identifier: Apache-2.0

// Draws through VSS chart_generator on the agent (POST /api/v1/incidents/charts). The tool
// stores the image in the agent's in-memory object store, so the image is read
// back from /static/ and deleted; the browser never talks to the agent.

import { randomUUID } from 'node:crypto';

import { ChartRenderError, type ChartDrawing, type ChartRenderer } from '@/modules/dashboard/domain/ChartRenderer';

const OUTPUT_DIR = 'dashboard-charts';
const TIMEOUT_MS = 30_000;

/** A pie has no axis to read a value from, so each label carries its figure. Empty slices are left out. */
function chartData({ chartType, title, categoryLabel, valueLabel, series, rows }: ChartDrawing) {
  if (chartType === 'pie') {
    const key = series[0]?.key ?? '';
    const slices = rows.filter((row) => row.values[key]);
    return {
      chart_file_format: 'png',
      title,
      sizes: slices.map((row) => row.values[key]),
      labels: slices.map((row) => `${row.category} (${row.values[key]})`),
    };
  }
  return {
    chart_file_format: 'png',
    title,
    x_categories: rows.map((row) => row.category),
    series: Object.fromEntries(series.map(({ key, label }) => [label, rows.map((row) => row.values[key] ?? 0)])),
    x_label: categoryLabel,
    y_label: valueLabel,
  };
}

function objectKey(body: unknown): string {
  const key = (Array.isArray(body) ? (body[0] as { object_store_key?: unknown } | undefined) : undefined)?.object_store_key;
  if (typeof key !== 'string' || !key) throw new ChartRenderError('The chart service returned no image');
  return key;
}

export class AgentChartRenderer implements ChartRenderer {
  private readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  private async fetch(path: string, init: RequestInit): Promise<Response> {
    const response = await fetch(`${this.baseUrl}${path}`, { ...init, cache: 'no-store', signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (!response.ok) throw new ChartRenderError(`The chart service returned HTTP ${response.status}`);
    return response;
  }

  async draw(drawing: ChartDrawing): Promise<string> {
    try {
      const drawn = await this.fetch('/api/v1/incidents/charts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        // A unique name per request, so two people can never receive each other's image.
        body: JSON.stringify({ charts_data: [chartData(drawing)], output_dir: OUTPUT_DIR, file_prefix: `${randomUUID()}_` }),
      });
      const key = objectKey(await drawn.json());
      const image = await (await this.fetch(`/static/${key}`, { method: 'GET' })).arrayBuffer();
      // The image is in hand, so a failed clean-up costs only a little agent memory until its next restart.
      await this.fetch(`/static/${key}`, { method: 'DELETE' }).catch(() => undefined);
      return `data:image/png;base64,${Buffer.from(image).toString('base64')}`;
    } catch (error) {
      if (error instanceof ChartRenderError) throw error;
      throw new ChartRenderError(`Could not reach the chart service: ${error instanceof Error ? error.message : String(error)}`);
    }
  }
}
