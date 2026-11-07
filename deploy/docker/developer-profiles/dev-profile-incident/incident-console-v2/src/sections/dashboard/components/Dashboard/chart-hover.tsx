// SPDX-License-Identifier: Apache-2.0

import { Rectangle, Sector } from 'recharts';

/** How much darker the hovered mark gets: its own colour mixed with black, so its meaning stays. */
export const darken = (color: string) => `color-mix(in srgb, ${color} 72%, black)`;

/** Extra thickness of a hovered bar and extra reach of a hovered donut slice, in px. */
const BAR_GROW = 6;
export const SLICE_GROW = 8;

// The pop-out is drawn the instant the chart reports the active mark; the short scale-in is the only motion and is
// switched off under prefers-reduced-motion (styles.css, .chart-pop), which keeps the darker colour.
type BarShapeProps = React.ComponentProps<typeof Rectangle> & { fill?: string };

/** Recharts' `activeBar` for a horizontal bar: darker and thicker, drawn over its neighbours without moving them. */
export function PopBar(props: BarShapeProps) {
  const { x = 0, y = 0, height = 0, fill = 'currentColor', ...rest } = props;
  return (
    <g className="chart-pop">
      <Rectangle {...rest} fill={darken(fill)} height={Number(height) + BAR_GROW} x={x} y={Number(y) - BAR_GROW / 2} />
    </g>
  );
}

type SectorProps = React.ComponentProps<typeof Sector> & { fill?: string };

/** `activeShape` of the donut: the hovered slice reaches outward and darkens. */
export function PopSector(props: SectorProps) {
  const { outerRadius = 0, fill = 'currentColor', ...rest } = props;
  return (
    <g className="chart-pop">
      <Sector {...rest} fill={darken(fill)} outerRadius={Number(outerRadius) + SLICE_GROW} />
    </g>
  );
}

/** `inactiveShape` of the donut: the other slices step back a little, so the hovered one reads. */
export function DimSector(props: SectorProps) {
  return <Sector {...props} fillOpacity={0.55} />;
}
