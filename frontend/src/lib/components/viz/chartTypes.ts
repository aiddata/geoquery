export type SingleColCard = {
  id: string;
  type: 'histogram' | 'top_bar' | 'bottom_bar' | 'binary_bar' | 'box_plot';
  column: string;
};

export type TimeSeriesCard = {
  id: string;
  type: 'time_series';
  datasetKey: string;
  columns: string[];
  aggregateMode: 'all' | 'mean' | 'band';
};

export type ScatterCard = {
  id: string;
  type: 'scatter';
  xCol: string;
  yCol: string;
};

export type CorrelationCard = {
  id: string;
  type: 'correlation';
  columns: string[];
};

export type ChartCard =
  | SingleColCard
  | TimeSeriesCard
  | ScatterCard
  | CorrelationCard;

export const CHART_TYPES: { value: ChartCard['type']; label: string; multi: boolean }[] = [
  { value: 'histogram',    label: 'Distribution',        multi: false },
  { value: 'top_bar',     label: 'Top Values',           multi: false },
  { value: 'bottom_bar',  label: 'Bottom Values',        multi: false },
  { value: 'binary_bar',  label: 'Present / Absent',     multi: false },
  { value: 'box_plot',    label: 'Box Plot by Group',    multi: false },
  { value: 'time_series', label: 'Time Series',          multi: true  },
  { value: 'scatter',     label: 'Scatter Plot',         multi: true  },
  { value: 'correlation', label: 'Correlation Matrix',   multi: true  },
];
