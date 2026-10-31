// SPDX-License-Identifier: Apache-2.0

// ChartRenderer: draws figures our code has already fetched as a static image.
// It chooses nothing about the data: it only draws what it is given.

import type { GeneratedChart } from '@/modules/dashboard/domain/generated-chart';

export type ChartDrawing = Pick<GeneratedChart, 'chartType' | 'title' | 'categoryLabel' | 'valueLabel' | 'series' | 'rows'>;

export interface ChartRenderer {
  /** The drawn chart as a data URL. Throws ChartRenderError when it could not be drawn. */
  draw(drawing: ChartDrawing): Promise<string>;
}

export class ChartRenderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ChartRenderError';
  }
}
