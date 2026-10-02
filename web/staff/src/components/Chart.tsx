import { useId, useState, type ReactElement } from "react";

import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { strings } from "@/strings";

/** One plotted value: `x` is a category such as a YYYY-MM-DD date, in sort order. */
export interface ChartPoint {
  x: string;
  y: number;
}

export interface ChartSeries {
  label: string;
  points: ChartPoint[];
}

export interface ChartProps {
  title: string;
  /** One sentence, shown above the chart (EXPERIENCE.md Chart pattern). */
  summary: string;
  series: ChartSeries[];
  /** How a value reads, on the chart and in its table. */
  format: (value: number) => string;
  /** The table's heading for `x`; "Date" when not given. */
  xLabel?: string;
  /** What `y` is, for the table heading and the range line ("Price"); "Value"
   * when not given. */
  yLabel?: string;
}

// Series are told apart by marker shape and line dash as well as colour, so colour is
// never the only cue (UX-DR18, WCAG 1.1.1 and 1.4.1). Colours are neutral design
// tokens (index.css has no chart tokens), never the functional ones (destructive and
// the like), each at least 3:1 on the background (WCAG 1.4.11).
const SHAPES = [
  "circle",
  "square",
  "triangle",
  "diamond",
  "cross",
  "ring",
] as const;
type Shape = (typeof SHAPES)[number];
const COLOURS: readonly [string, ...string[]] = [
  "var(--foreground)",
  "var(--primary)",
  "var(--ring)",
  "var(--accent-foreground)",
];
const DASHES = ["", "8 4", "2 4", "12 4 2 4"];

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const WIDTH = 640;
const HEIGHT = 280;
const PAD = 16;
const MARK = 6;

function style(index: number) {
  return {
    shape: SHAPES[index % SHAPES.length] as Shape,
    colour: COLOURS[index % COLOURS.length] ?? COLOURS[0],
    dash: DASHES[index % DASHES.length] ?? "",
  };
}

function Marker({
  shape,
  x,
  y,
  colour,
}: {
  shape: Shape;
  x: number;
  y: number;
  colour: string;
}): ReactElement {
  const common = {
    "data-marker": shape,
    stroke: colour,
    strokeWidth: 2,
    fill: colour,
  };
  switch (shape) {
    case "square":
      return (
        <rect
          {...common}
          x={x - MARK}
          y={y - MARK}
          width={MARK * 2}
          height={MARK * 2}
        />
      );
    case "triangle":
      return (
        <polygon
          {...common}
          points={`${x},${y - MARK} ${x + MARK},${y + MARK} ${x - MARK},${y + MARK}`}
        />
      );
    case "diamond":
      return (
        <polygon
          {...common}
          points={`${x},${y - MARK} ${x + MARK},${y} ${x},${y + MARK} ${x - MARK},${y}`}
        />
      );
    case "cross":
      return (
        <path
          {...common}
          fill="none"
          strokeWidth={3}
          d={`M${x - MARK} ${y - MARK}L${x + MARK} ${y + MARK}M${x + MARK} ${y - MARK}L${x - MARK} ${y + MARK}`}
        />
      );
    case "ring":
      return (
        <circle
          {...common}
          className="fill-background"
          cx={x}
          cy={y}
          r={MARK}
        />
      );
    default:
      return <circle {...common} cx={x} cy={y} r={MARK} />;
  }
}

/**
 * A line chart in inline SVG (Story 5.3; reused by Stories 5.5 and 5.6), with no
 * charting library. Its one-sentence summary sits above it, each series has a text
 * label and its own marker, and **View as table** lists every plotted value
 * (EXPERIENCE.md Chart pattern). It only draws the values it is given.
 */
export function Chart({
  title,
  summary,
  series,
  format,
  xLabel,
  yLabel,
}: ChartProps) {
  const ids = { title: useId(), summary: useId() };
  const [asTable, setAsTable] = useState(false);
  const s = strings.chart;

  const xs = [...new Set(series.flatMap((one) => one.points.map((p) => p.x)))];
  xs.sort();
  const ys = series.flatMap((one) => one.points.map((p) => p.y));
  const low = ys.length > 0 ? Math.min(...ys) : 0;
  const high = ys.length > 0 ? Math.max(...ys) : 0;
  // YYYY-MM-DD dates sit in proportion to time, so a trend reads true; any other
  // category is evenly spaced.
  const dated = xs.length > 0 && xs.every((x) => ISO_DATE.test(x));
  const position = (x: string) => (dated ? Date.parse(x) : xs.indexOf(x));
  const first = xs.length > 0 ? position(xs[0] ?? "") : 0;
  const last = xs.length > 0 ? position(xs[xs.length - 1] ?? "") : 0;
  const xAt = (x: string) =>
    last === first
      ? WIDTH / 2
      : PAD + ((position(x) - first) * (WIDTH - 2 * PAD)) / (last - first);
  const yAt = (y: number) =>
    high === low
      ? HEIGHT / 2
      : HEIGHT - PAD - ((y - low) * (HEIGHT - 2 * PAD)) / (high - low);

  return (
    <section aria-labelledby={ids.title} className="flex flex-col gap-2">
      <h2 id={ids.title} className="text-lg font-semibold">
        {title}
      </h2>
      <p id={ids.summary} className="max-w-prose">
        {summary}
      </p>
      <div>
        <Button
          type="button"
          variant="outline"
          onClick={() => setAsTable((on) => !on)}
        >
          {asTable ? s.viewChart : s.viewTable}
        </Button>
      </div>

      {asTable ? (
        <Table scrollLabel={title}>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">{s.series}</TableHead>
              <TableHead scope="col">{xLabel ?? s.x}</TableHead>
              <TableHead scope="col" className="text-right">
                {yLabel ?? s.value}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {series.flatMap((one, index) =>
              one.points.map((point, n) => (
                <TableRow key={`${index}-${n}`} data-testid="chart-row">
                  <TableCell>{one.label}</TableCell>
                  <TableCell className="numeric">{point.x}</TableCell>
                  <TableCell className="numeric text-right">
                    {format(point.y)}
                  </TableCell>
                </TableRow>
              )),
            )}
          </TableBody>
        </Table>
      ) : (
        <div className="flex flex-col gap-2">
          <p className="numeric text-sm text-muted-foreground">
            {s.range(yLabel ?? s.value, format(low), format(high))}
          </p>
          <svg
            role="img"
            aria-labelledby={`${ids.title} ${ids.summary}`}
            viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
            className="h-auto w-full max-w-3xl rounded-md border"
          >
            {[PAD, HEIGHT - PAD].map((y) => (
              <line
                key={y}
                x1={0}
                x2={WIDTH}
                y1={y}
                y2={y}
                className="stroke-border"
              />
            ))}
            {series.map((one, index) => {
              const { shape, colour, dash } = style(index);
              const points = [...one.points].sort((a, b) =>
                a.x < b.x ? -1 : a.x > b.x ? 1 : 0,
              );
              return (
                <g key={index} data-series={one.label}>
                  <polyline
                    points={points
                      .map((p) => `${xAt(p.x)},${yAt(p.y)}`)
                      .join(" ")}
                    fill="none"
                    stroke={colour}
                    strokeWidth={2}
                    strokeDasharray={dash || undefined}
                  />
                  {points.map((p, n) => (
                    <Marker
                      key={n}
                      shape={shape}
                      x={xAt(p.x)}
                      y={yAt(p.y)}
                      colour={colour}
                    />
                  ))}
                </g>
              );
            })}
          </svg>
          {xs.length > 0 ? (
            <p className="numeric text-sm text-muted-foreground">
              {s.range(
                dated ? s.dates : (xLabel ?? s.x),
                xs[0] ?? "",
                xs[xs.length - 1] ?? "",
              )}
            </p>
          ) : null}
          <ul aria-label={s.legend} className="flex flex-wrap gap-x-4 gap-y-1">
            {series.map((one, index) => {
              const { shape, colour, dash } = style(index);
              return (
                <li key={index} className="flex items-center gap-2 text-sm">
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 32 16"
                    className="h-4 w-8 shrink-0"
                  >
                    <line
                      x1={0}
                      x2={32}
                      y1={8}
                      y2={8}
                      stroke={colour}
                      strokeWidth={2}
                      strokeDasharray={dash || undefined}
                    />
                    <Marker shape={shape} x={16} y={8} colour={colour} />
                  </svg>
                  <span>{one.label}</span>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </section>
  );
}
