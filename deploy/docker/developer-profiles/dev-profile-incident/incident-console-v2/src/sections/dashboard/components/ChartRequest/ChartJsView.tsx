// SPDX-License-Identifier: Apache-2.0
'use client';

import { Chart as ChartJS, type ChartData, type ChartOptions, type ChartType, registerables } from 'chart.js';
import { Chart } from 'react-chartjs-2';

import { chartJsOptions } from '@/modules/dashboard/domain/chart-config';
import type { ChartJsConfig } from '@/modules/dashboard/domain/generated-chart';

ChartJS.register(...registerables);

/**
 * Draws a configuration the agent built, with the figures already checked against the rows. The
 * wrapper is the image for assistive technology, with a sentence naming the chart and its totals;
 * the Table tab next to it gives every figure.
 */
export function ChartJsView({ config, label }: { config: ChartJsConfig; label: string }) {
  return (
    <div aria-label={label} className="relative h-72 w-full min-w-0" role="img">
      <Chart data={config.data as ChartData} options={chartJsOptions(config) as ChartOptions} type={config.type as ChartType} />
    </div>
  );
}
