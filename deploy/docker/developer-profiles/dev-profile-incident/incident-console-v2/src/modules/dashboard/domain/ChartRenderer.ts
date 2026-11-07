// SPDX-License-Identifier: Apache-2.0

// ChartRenderer: the VSS chart_generator builds the chart from figures our code has already fetched.
// It chooses nothing about the data: it places the figures it is given, in a Chart.js configuration
// the browser draws, or as a static PNG when no configuration comes back.

import type { DrawnKind, GeneratedChart } from '@/modules/dashboard/domain/generated-chart';

export type ChartDrawing = Pick<GeneratedChart, 'title' | 'categoryLabel' | 'valueLabel' | 'secondValueLabel' | 'series' | 'rows'> & {
  chartKind: DrawnKind;
  /** One colour per donut slice or bubble, in row order; null for every other kind. */
  sliceColors: string[] | null;
};

export interface ChartRenderer {
  /**
   * The Chart.js configuration with these figures placed in it, as the agent sent it; null when the
   * service returned none or cannot build one (an agent without Chart.js output), so the caller draws the PNG.
   * The caller checks it against the rows. Throws ChartRenderError when the call fails any other way.
   */
  configure(drawing: ChartDrawing): Promise<unknown>;
  /** The static PNG as a data URL (the fallback). Throws ChartRenderError when it could not be drawn. */
  draw(drawing: ChartDrawing): Promise<string>;
}

export class ChartRenderError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ChartRenderError';
  }
}
